"""
Aetna policy scraper.

Scrapes policies from Aetna's website using Selenium WebDriver.
Converts HTML content to markdown format to preserve document structure.
Based on proven working implementation.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import requests
import structlog
from typing import List, Optional
import sys
import os

# Add parent directories to path for imports
sys.path.insert(0, '/var/task')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from common.policy_models import PolicyExtractionResult

logger = structlog.get_logger(__name__)


def scrape_aetna_policies(service_code: str) -> List[PolicyExtractionResult]:
    """
    Scrape Aetna policies for a given service code.
    
    Args:
        service_code: CPT/HCPCS/RxNorm/J-code to search for
        
    Returns:
        List of PolicyExtractionResult objects
    """
    logger.info("Starting Aetna policy scrape", service_code=service_code)
    
    # Setup Chrome driver with Lambda-specific configuration
    chrome_options = Options()
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
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Use environment variables for Chrome paths (set in Dockerfile)
    chrome_bin = os.environ.get('CHROME_BIN', '/usr/bin/google-chrome')
    chromedriver_path = os.environ.get('CHROMEDRIVER_PATH', '/usr/local/bin/chromedriver')
    
    chrome_options.binary_location = chrome_bin
    
    # Create service object for ChromeDriver
    service = Service(executable_path=chromedriver_path)
    
    driver = webdriver.Chrome(
        service=service,
        options=chrome_options
    )
    driver.implicitly_wait(10)
    
    # Execute script to hide webdriver property
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    try:
        # Construct search URL
        search_url = f"https://www.aetna.com/health-care-professionals/clinical-policy-bulletins/medical-clinical-policy-bulletins/medical-clinical-policy-bulletins-search-results.html?query={service_code}&offset=0"
        
        logger.info("Navigating to search URL", url=search_url)
        driver.get(search_url)
        
        # Wait for search results to load
        try:
            WebDriverWait(driver, 20).until(
                lambda d: (
                    len(d.find_elements(By.CSS_SELECTOR, 'a[href*="/cpb/"]')) > 0 or
                    "No results found" in d.page_source or
                    len(d.find_elements(By.TAG_NAME, "a")) > 50
                )
            )
            time.sleep(5)  # Reduced wait time  # nosemgrep: arbitrary-sleep
        except:
            logger.warning("Wait timeout, proceeding anyway")
            time.sleep(5)  # Reduced wait time  # nosemgrep: arbitrary-sleep
        
        # Parse page and extract policies
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        policy_results = _extract_policy_links_and_content(soup, driver, service_code)
        
        logger.info(
            "Scraping complete",
            service_code=service_code,
            policies_found=len(policy_results)
        )
        
        return policy_results
        
    finally:
        driver.quit()


def _extract_policy_links_and_content(
    soup: BeautifulSoup,
    driver,
    service_code: str
) -> List[PolicyExtractionResult]:
    """Extract policy links and their content."""
    
    logger.info("Looking for policy links")
    
    # Find all policy links (contain /cpb/ in URL)
    policy_links = []
    links = soup.select('a[href*="/cpb/"]')
    
    for link in links:
        href = link.get('href')
        text = link.get_text(strip=True)
        
        if href and len(text) > 5:
            # Make full URL
            if href.startswith('/'):
                full_url = "https://www.aetna.com" + href
            elif href.startswith('http'):
                full_url = href
            else:
                continue
            
            # Check if it's an actual policy link
            if '/cpb/' in href.lower():
                # Avoid duplicates
                if not any(p['url'] == full_url for p in policy_links):
                    policy_links.append({
                        'url': full_url,
                        'title': text
                    })
                    logger.info("Found policy", title=text, url=full_url)
    
    if not policy_links:
        logger.warning("No policy links found")
        return []
    
    # Limit to first 10 policies
    first_10_policies = policy_links[:10]
    logger.info(f"Extracting content from {len(first_10_policies)} policies")
    
    policy_results = []
    
    # Extract content from each policy
    for i, policy in enumerate(first_10_policies, 1):
        try:
            logger.info(
                "Extracting policy content",
                index=i,
                title=policy['title'],
                url=policy['url']
            )
            
            # Navigate to policy page
            driver.get(policy['url'])
            time.sleep(3)  # Reduced wait time  # nosemgrep: arbitrary-sleep
            
            # Check if blocked
            page_source = driver.page_source
            page_title = driver.title.lower()
            
            if _is_blocked(page_source, page_title):
                logger.warning("Selenium access blocked, trying direct fetch")
                
                # Try direct HTTP fetch as fallback
                content = _fetch_policy_content_directly(policy['url'])
                extraction_method = "direct_fetch_markdown"
                
                if not content or len(content) < 1000:
                    logger.warning("Direct fetch failed, using access restriction message")
                    content = f"# Access Restricted\n\nPolicy found but access restricted by website security.\n\n**Policy Title:** {policy['title']}\n\n**URL:** {policy['url']}\n\nPlease access manually through the Aetna provider portal."
                    extraction_method = "blocked"
            else:
                # Extract content normally with markdown formatting
                content = _extract_clean_text(page_source)
                extraction_method = "selenium_markdown"
            
            if content:
                policy_results.append(PolicyExtractionResult(
                    url=policy['url'],
                    content=content,
                    title=policy['title'],
                    search_code=service_code,
                    extraction_method=extraction_method
                ))
                logger.info(
                    "Successfully extracted policy",
                    title=policy['title'],
                    content_length=len(content),
                    method=extraction_method
                )
            
        except Exception as e:
            logger.error(
                "Error extracting policy",
                title=policy['title'],
                error=str(e)
            )
            continue
    
    return policy_results


def _is_blocked(page_source: str, page_title: str) -> bool:
    """Check if access is blocked."""
    return (
        'incapsula' in page_source.lower() or
        'blocked' in page_title or
        'access denied' in page_title or
        len(page_source) < 500
    )


def _extract_clean_text(page_source: str) -> str:
    """
    Extract content from HTML and convert to markdown format.
    
    Preserves document structure including:
    - Section headers with hierarchy
    - Tables with proper formatting
    - Lists (ordered and unordered)
    - Code blocks and inline code
    
    Args:
        page_source: Raw HTML content
        
    Returns:
        Markdown-formatted content
    """
    soup = BeautifulSoup(page_source, 'html.parser')
    
    # Remove unwanted elements
    for element in soup(["script", "style", "nav", "header", "footer"]):
        element.decompose()
    
    # Get main content area
    body = soup.find('body')
    if body:
        # Remove navigation elements
        for nav_elem in body.find_all(['nav', 'header', 'footer']):
            nav_elem.decompose()
        
        content_html = str(body)
    else:
        content_html = str(soup)
    
    # Convert HTML to markdown with formatting preservation
    markdown_content = md(
        content_html,
        heading_style="ATX",  # Use # style headers
        bullets="-",  # Use - for unordered lists
        strip=['a'],  # Remove link tags but keep text
        escape_asterisks=False,  # Don't escape * in medical terms
        escape_underscores=False  # Don't escape _ in medical terms
    )
    
    # Clean up excessive whitespace while preserving structure
    lines = []
    prev_empty = False
    for line in markdown_content.split('\n'):
        stripped = line.strip()
        # Keep line if it has content, or if it's a single empty line between sections
        if stripped:
            lines.append(stripped)
            prev_empty = False
        elif not prev_empty:
            lines.append('')
            prev_empty = True
    
    clean_content = '\n'.join(lines)
    
    logger.info(
        "Converted HTML to markdown",
        original_length=len(page_source),
        markdown_length=len(clean_content)
    )
    
    return clean_content


def _fetch_policy_content_directly(url: str) -> Optional[str]:
    """Fetch policy content directly using requests as fallback."""
    try:
        logger.info("Attempting direct HTTP fetch", url=url)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        if len(response.text) > 1000:
            content = _extract_clean_text(response.text)
            logger.info("Direct fetch successful", content_length=len(content))
            return content
        else:
            logger.warning("Direct fetch returned minimal content")
            return None
            
    except Exception as e:
        logger.error("Direct fetch failed", error=str(e))
        return None
