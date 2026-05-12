"""
Humana Policy Scraper

Scrapes policies from Humana's Medical Coverage Policy (MCP) website.
Handles dynamic JavaScript links and PDF downloads.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import pypdf
import io
import os
import tempfile
import requests
import structlog
from typing import List, Dict, Optional
from datetime import datetime

logger = structlog.get_logger(__name__)


def setup_chrome_driver(download_dir: str) -> webdriver.Chrome:
    """
    Setup Chrome driver with download preferences for PDF files.
    Lambda-optimized configuration.
    
    Args:
        download_dir: Directory for PDF downloads
        
    Returns:
        Configured Chrome WebDriver instance
    """
    chrome_options = Options()
    # Use new headless mode (more efficient and stable in Lambda)
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--single-process")
    chrome_options.add_argument("--disable-dev-tools")
    chrome_options.add_argument("--no-zygote")
    chrome_options.add_argument("--window-size=1280,1024")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    
    # Configure download settings for PDFs
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.implicitly_wait(10)
    
    # Execute script to hide webdriver property
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver


def extract_pdf_content_from_file(pdf_path: str) -> Optional[str]:
    """
    Extract text content from a local PDF file using pypdf.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Extracted text content or None if extraction fails
    """
    try:
        logger.info("Extracting PDF content", pdf_path=pdf_path)
        
        with open(pdf_path, 'rb') as pdf_file:
            pdf_reader = pypdf.PdfReader(pdf_file)
            text_content = []
            
            logger.info("PDF opened", pages=len(pdf_reader.pages))
            
            for page_num, page in enumerate(pdf_reader.pages):
                try:
                    page_text = page.extract_text()
                    if page_text.strip():
                        text_content.append(f"--- Page {page_num + 1} ---")
                        text_content.append(page_text.strip())
                except Exception as e:
                    logger.warning(
                        "Error extracting page",
                        page_num=page_num + 1,
                        error=str(e)
                    )
                    continue
            
            if not text_content:
                logger.warning("No text content extracted from PDF")
                return None
            
            full_content = '\n\n'.join(text_content)
            
            logger.info(
                "PDF extraction successful",
                char_count=len(full_content),
                pages_extracted=len(text_content) // 2
            )
            
            return full_content
            
    except Exception as e:
        logger.error("Error extracting PDF content", error=str(e), error_type=type(e).__name__)
        return None


def get_first_10_policies(
    soup: BeautifulSoup,
    driver: webdriver.Chrome,
    download_dir: str,
    service_code: str
) -> List[Dict[str, str]]:
    """
    Get the first 10 policies from search results and download their PDFs.
    
    Args:
        soup: BeautifulSoup object of search results page
        driver: Selenium WebDriver instance
        download_dir: Directory for PDF downloads
        service_code: Service code being searched
        
    Returns:
        List of policy dictionaries with url, content, and title
    """
    logger.info("Finding policy links to click")
    
    # Look for the results GridView table
    results_table = soup.find('table', id=lambda x: x and 'GridView' in x)
    
    if not results_table:
        logger.warning("No results GridView table found")
        return []
    
    logger.info("Found GridView table")
    
    # Find all policy rows (skip header row)
    policy_links = []
    rows = results_table.find_all('tr')
    
    logger.info("Parsing table rows", total_rows=len(rows))
    
    for i, row in enumerate(rows[1:], 1):  # Skip header row
        links = row.find_all('a', href=True)
        
        logger.info(f"Row {i}", links_found=len(links))
        
        for link in links:
            href = link.get('href')
            text = link.get_text(strip=True)
            name_attr = link.get('name', '')
            
            logger.info(f"Link in row {i}", 
                       href=href[:100] if href else None,
                       text=text[:50] if text else None,
                       name=name_attr)
            
            # Look for JavaScript postback links with policy names
            if href and 'javascript:__doPostBack' in href and len(text) > 10:
                policy_links.append({
                    'title': text,
                    'xpath': f"//a[contains(@href, 'GridView$ctl0{i+1}$HrefLink')]",
                    'row_num': i,
                    'object_id': name_attr
                })
                logger.info("Found policy link", row_num=i, title=text, object_id=name_attr)
    
    if not policy_links:
        logger.warning("No policy links found in GridView")
        return []
    
    logger.info("Found policy links", count=len(policy_links))
    
    # Limit to first 10 policies
    first_10_policies = policy_links[:10]
    logger.info("Processing first 10 policies", count=len(first_10_policies))
    
    policy_results = []
    browser_alive = True
    
    for i, policy in enumerate(first_10_policies):
        try:
            logger.info(
                "Clicking policy link",
                index=i+1,
                title=policy['title'],
                object_id=policy.get('object_id', 'N/A')
            )
            
            # Check if browser is still alive, restart if needed
            if not browser_alive:
                logger.info("Browser crashed, restarting for next policy")
                try:
                    driver.quit()
                except:  # nosec B110
                    pass
                
                driver = setup_chrome_driver(download_dir)
                driver.get("https://mcp.humana.com")
                driver.add_cookie({
                    'name': 'DisclaimerAccepted',
                    'value': 'true',
                    'domain': 'mcp.humana.com',
                    'path': '/'
                })
                
                # Navigate back to search results
                search_url = (
                    f"https://mcp.humana.com/tad/tad_new/Search.aspx?"
                    f"criteria={service_code}&searchtype=freetext&policyType=both"
                )
                driver.get(search_url)
                time.sleep(5)  # nosemgrep: arbitrary-sleep
                browser_alive = True
            
            # Clear existing downloads
            existing_files = [f for f in os.listdir(download_dir) if f.endswith('.pdf')]
            if existing_files:
                logger.info("Clearing existing downloads", count=len(existing_files))
                for f in existing_files:
                    os.remove(os.path.join(download_dir, f))
            
            # Use ASP.NET postback approach to download PDF
            object_id = policy.get('object_id', '')
            
            logger.info("Attempting ASP.NET postback download", object_id=object_id)
            
            downloaded_files = []
            
            try:
                # Get current page source to extract ViewState and EventValidation
                page_source = driver.page_source
                soup_current = BeautifulSoup(page_source, 'html.parser')
                
                # Extract ASP.NET form fields
                viewstate = soup_current.find('input', {'name': '__VIEWSTATE'})
                viewstate_value = viewstate['value'] if viewstate else ''
                
                viewstate_generator = soup_current.find('input', {'name': '__VIEWSTATEGENERATOR'})
                viewstate_generator_value = viewstate_generator['value'] if viewstate_generator else ''
                
                event_validation = soup_current.find('input', {'name': '__EVENTVALIDATION'})
                event_validation_value = event_validation['value'] if event_validation else ''
                
                logger.info("Extracted ASP.NET form fields",
                           has_viewstate=bool(viewstate_value),
                           has_generator=bool(viewstate_generator_value),
                           has_validation=bool(event_validation_value))
                
                # Get cookies from Selenium session
                selenium_cookies = driver.get_cookies()
                cookies_dict = {cookie['name']: cookie['value'] for cookie in selenium_cookies}
                
                # Construct the postback target
                # The link href is: javascript:__doPostBack('ctl00$ContentPlaceHolder1$MentorResultsGridView$ctl02$HrefLink','')
                event_target = f"ctl00$ContentPlaceHolder1$MentorResultsGridView$ctl0{policy['row_num']+1}$HrefLink"
                
                # Prepare form data for postback
                form_data = {
                    '__EVENTTARGET': event_target,
                    '__EVENTARGUMENT': '',
                    '__VIEWSTATE': viewstate_value,
                    '__VIEWSTATEGENERATOR': viewstate_generator_value,
                    '__EVENTVALIDATION': event_validation_value,
                }
                
                logger.info("Submitting ASP.NET postback",
                           event_target=event_target,
                           form_data_keys=list(form_data.keys()))
                
                # Submit the postback
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': driver.current_url,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': 'https://mcp.humana.com',
                }
                
                response = requests.post(  # nosemgrep: use-raise-for-status
                    driver.current_url,
                    data=form_data,
                    headers=headers,
                    cookies=cookies_dict,
                    timeout=30,
                    allow_redirects=True
                )
                
                logger.info("Postback response received",
                           status_code=response.status_code,
                           content_type=response.headers.get('Content-Type', 'unknown'),
                           content_length=len(response.content),
                           final_url=response.url)
                
                # Check if response is a PDF
                if response.status_code == 200:
                    if response.content[:4] == b'%PDF' or 'application/pdf' in response.headers.get('Content-Type', ''):
                        # It's a PDF!
                        pdf_filename = f"policy_{object_id}.pdf"
                        pdf_path = os.path.join(download_dir, pdf_filename)
                        
                        with open(pdf_path, 'wb') as f:
                            f.write(response.content)
                        
                        logger.info("PDF downloaded via postback",
                                   filename=pdf_filename,
                                   size=len(response.content))
                        
                        downloaded_files = [pdf_filename]
                        browser_alive = True
                    else:
                        # Not a PDF, might be a redirect page
                        logger.info("Postback response is not a PDF",
                                   content_start=response.content[:200])
                        
                        # Try to find PDF URL in the response
                        response_soup = BeautifulSoup(response.content, 'html.parser')
                        
                        # Look for PDF links or iframes
                        pdf_links = response_soup.find_all('a', href=lambda x: x and '.pdf' in x.lower())
                        iframes = response_soup.find_all('iframe')
                        
                        if pdf_links:
                            pdf_url = pdf_links[0]['href']
                            if not pdf_url.startswith('http'):
                                pdf_url = f"https://mcp.humana.com{pdf_url}" if pdf_url.startswith('/') else f"https://mcp.humana.com/{pdf_url}"
                            
                            logger.info("Found PDF link in response", url=pdf_url)
                            
                            pdf_response = requests.get(pdf_url, headers=headers, cookies=cookies_dict, timeout=30)  # nosemgrep: use-raise-for-status
                            if pdf_response.status_code == 200 and pdf_response.content[:4] == b'%PDF':
                                pdf_filename = f"policy_{object_id}.pdf"
                                pdf_path = os.path.join(download_dir, pdf_filename)
                                
                                with open(pdf_path, 'wb') as f:
                                    f.write(pdf_response.content)
                                
                                logger.info("PDF downloaded from link",
                                           filename=pdf_filename,
                                           size=len(pdf_response.content))
                                
                                downloaded_files = [pdf_filename]
                                browser_alive = True
                        elif iframes:
                            iframe_src = iframes[0].get('src', '')
                            if iframe_src:
                                if not iframe_src.startswith('http'):
                                    iframe_src = f"https://mcp.humana.com{iframe_src}" if iframe_src.startswith('/') else f"https://mcp.humana.com/{iframe_src}"
                                
                                logger.info("Found iframe in response", src=iframe_src)
                                
                                iframe_response = requests.get(iframe_src, headers=headers, cookies=cookies_dict, timeout=30)  # nosemgrep: use-raise-for-status
                                if iframe_response.status_code == 200 and iframe_response.content[:4] == b'%PDF':
                                    pdf_filename = f"policy_{object_id}.pdf"
                                    pdf_path = os.path.join(download_dir, pdf_filename)
                                    
                                    with open(pdf_path, 'wb') as f:
                                        f.write(iframe_response.content)
                                    
                                    logger.info("PDF downloaded from iframe",
                                               filename=pdf_filename,
                                               size=len(iframe_response.content))
                                    
                                    downloaded_files = [pdf_filename]
                                    browser_alive = True
                else:
                    logger.warning("Postback failed",
                                  status_code=response.status_code)
                
            except Exception as postback_error:
                logger.error("Error during ASP.NET postback",
                           error=str(postback_error),
                           error_type=type(postback_error).__name__)
                browser_alive = True
            
            if not downloaded_files:
                logger.warning("ASP.NET postback did not yield PDF")
                browser_alive = True
                continue
            
            if not downloaded_files:
                logger.warning("No PDF obtained", title=policy['title'])
                continue
            
            if downloaded_files:
                # Get the downloaded file
                pdf_file = downloaded_files[0]
                pdf_path = os.path.join(download_dir, pdf_file)
                
                logger.info("Processing downloaded PDF", filename=pdf_file)
                
                # Extract content
                content = extract_pdf_content_from_file(pdf_path)
                
                if content:
                    # Generate filename from policy title
                    safe_title = sanitize_filename(policy['title'])
                    
                    policy_results.append({
                        'url': f"humana_policy_{policy['row_num']}_{pdf_file}",
                        'content': content,
                        'title': policy['title'],
                        'filename': f"HumanaPolicy_{safe_title}.md",
                        'extraction_method': 'pypdf'
                    })
                    
                    logger.info(
                        "Policy extraction successful",
                        title=policy['title'],
                        char_count=len(content)
                    )
                else:
                    logger.warning(
                        "Failed to extract content",
                        title=policy['title'],
                        pdf_file=pdf_file
                    )
            else:
                logger.warning(
                    "No PDF downloaded",
                    title=policy['title']
                )
                
        except Exception as e:
            logger.error(
                "Error downloading policy",
                title=policy['title'],
                error=str(e),
                error_type=type(e).__name__
            )
            continue
    
    return policy_results


def sanitize_filename(title: str) -> str:
    """
    Sanitize policy title for use as filename.
    
    Args:
        title: Policy title
        
    Returns:
        Sanitized filename-safe string
    """
    # Replace spaces with underscores
    safe = title.replace(' ', '_')
    
    # Remove special characters
    safe = ''.join(c for c in safe if c.isalnum() or c == '_')
    
    # Limit length
    if len(safe) > 100:
        safe = safe[:100]
    
    return safe


def scrape_humana_policies(service_code: str, download_dir: str = None) -> List[Dict[str, str]]:
    """
    Scrape Humana policies for a given service code.
    
    Args:
        service_code: CPT/HCPCS code to search for
        download_dir: Directory for PDF downloads. If None, a secure temp directory is created.
        
    Returns:
        List of policy dictionaries with url, content, title, filename, extraction_method
    """
    # Use tempfile for secure temp directory if none provided
    if download_dir is None:
        download_dir = tempfile.mkdtemp(prefix="humana_downloads_")
    else:
        os.makedirs(download_dir, exist_ok=True)
    
    logger.info(
        "Starting Humana policy scrape",
        service_code=service_code,
        download_dir=download_dir
    )
    
    driver = None
    
    try:
        # Setup Chrome driver
        driver = setup_chrome_driver(download_dir)
        
        # Set disclaimer cookie to bypass alert
        driver.get("https://mcp.humana.com")
        driver.add_cookie({
            'name': 'DisclaimerAccepted',
            'value': 'true',
            'domain': 'mcp.humana.com',
            'path': '/'
        })
        logger.info("Set disclaimer cookie to bypass alert")
        
        # Construct search URL
        search_url = (
            f"https://mcp.humana.com/tad/tad_new/Search.aspx?"
            f"criteria={service_code}&searchtype=freetext&policyType=both"
        )
        
        logger.info("Navigating to search URL", url=search_url)
        
        driver.get(search_url)
        
        # Wait for page to load
        time.sleep(3)  # nosemgrep: arbitrary-sleep
        
        # Debug: Check initial page state
        logger.info("Page loaded", 
                   title=driver.title,
                   current_url=driver.current_url)
        
        # Wait for search results and JavaScript to load
        try:
            # Wait for the GridView table to appear with results
            WebDriverWait(driver, 30).until(
                lambda d: len([t for t in d.find_elements(By.TAG_NAME, "table") 
                              if 'GridView' in t.get_attribute('id') and 
                              len(t.find_elements(By.TAG_NAME, "tr")) > 1]) > 0
            )
            logger.info("GridView table with results found")
            
            # Give JavaScript additional time to populate
            time.sleep(5)  # nosemgrep: arbitrary-sleep
            
        except Exception as e:
            logger.warning("Timeout waiting for search results", error=str(e))
        
        # Parse search results
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # Debug: Check what tables we have
        all_tables = soup.find_all('table')
        logger.info("Tables found on page", count=len(all_tables))
        
        gridview_tables = [t for t in all_tables if t.get('id') and 'GridView' in t.get('id')]
        logger.info("GridView tables found", count=len(gridview_tables))
        
        if gridview_tables:
            for i, table in enumerate(gridview_tables):
                rows = table.find_all('tr')
                logger.info(f"GridView table {i}", 
                           table_id=table.get('id'),
                           row_count=len(rows))
                
                # Log first few rows
                if len(rows) > 1:
                    for j, row in enumerate(rows[:3]):
                        cells = row.find_all(['td', 'th'])
                        logger.info(f"Row {j}", 
                                   cell_count=len(cells),
                                   row_html=str(row)[:500])
        
        # Get first 10 policies
        policy_results = get_first_10_policies(soup, driver, download_dir, service_code)
        
        if not policy_results:
            logger.warning("No policies found", service_code=service_code)
            return []
        
        logger.info(
            "Humana scrape complete",
            service_code=service_code,
            policies_found=len(policy_results)
        )
        
        return policy_results
        
    except Exception as e:
        logger.error(
            "Error scraping Humana policies",
            service_code=service_code,
            error=str(e),
            error_type=type(e).__name__
        )
        return []
        
    finally:
        if driver:
            driver.quit()
            logger.info("Chrome driver closed")
