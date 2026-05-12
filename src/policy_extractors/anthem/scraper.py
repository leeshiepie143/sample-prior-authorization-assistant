"""
Anthem Policy Scraper

Scrapes policies from Anthem's clinical guidelines website.
Handles state-specific searches with fallback patterns.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import structlog
from typing import List, Dict, Optional

logger = structlog.get_logger(__name__)


def setup_chrome_driver() -> webdriver.Chrome:
    """
    Setup Chrome driver for web scraping with Lambda-optimized configuration.
    
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
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.implicitly_wait(10)
    
    # Execute script to hide webdriver property
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver


def extract_policy_identifier(url: str) -> str:
    """
    Extract policy identifier from Anthem URL.
    
    Examples:
    - https://www.anthem.com/medpolicies/abcbs/active/gl_pw_e000366.html → gl_pw_e000366
    - https://www.anthem.com/medpolicies/policies/mp_pw_a050053.html → mp_pw_a050053
    
    Args:
        url: Policy URL
        
    Returns:
        Policy identifier
    """
    # Extract filename from URL
    if '/medpolicies/' in url:
        # Get the last part of the path
        parts = url.rstrip('/').split('/')
        filename = parts[-1]
        
        # Remove .html extension
        if filename.endswith('.html'):
            filename = filename[:-5]
        
        return filename
    
    # Fallback: use last part of URL
    return url.split('/')[-1].replace('.html', '')


def sanitize_filename(identifier: str) -> str:
    """
    Sanitize policy identifier for use as filename.
    
    Args:
        identifier: Policy identifier
        
    Returns:
        Sanitized filename-safe string
    """
    # Replace special characters
    safe = identifier.replace(' ', '_')
    safe = ''.join(c for c in safe if c.isalnum() or c in ['_', '-'])
    
    # Limit length
    if len(safe) > 100:
        safe = safe[:100]
    
    return safe


def extract_clean_text_as_markdown(page_source: str) -> str:
    """
    Extract content from HTML and convert to markdown format.
    Preserves document structure including headers, tables, and lists.
    
    Args:
        page_source: HTML page source
        
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
        if stripped:
            lines.append(stripped)
            prev_empty = False
        elif not prev_empty:
            lines.append('')
            prev_empty = True
    
    return '\n'.join(lines)


def is_actual_policy_link(href: str, text: str) -> bool:
    """
    Check if a link is actually a medical policy (not navigation or generic pages).
    
    Args:
        href: Link href attribute
        text: Link text
        
    Returns:
        True if this is a policy link
    """
    href_lower = href.lower()
    
    # All policy links must contain /medpolicies/ in the URL
    return '/medpolicies/' in href_lower and len(text) > 5


def get_first_10_anthem_policies(
    soup: BeautifulSoup,
    driver: webdriver.Chrome,
    service_code: str
) -> List[Dict[str, str]]:
    """
    Get the first 10 policies from Anthem search results.
    
    Args:
        soup: BeautifulSoup object of search results page
        driver: Selenium WebDriver instance
        service_code: Service code being searched
        
    Returns:
        List of policy dictionaries with url, content, title, filename
    """
    logger.info("Looking for Anthem policy results", total_links=len(soup.find_all('a')))
    
    # Look for medical policy links - all policy links contain /medpolicies/
    policy_links = []
    
    # Strategy 1: Find all links with /medpolicies/ in href using CSS selector
    policy_selectors = ['a[href*="/medpolicies/"]']
    
    for selector in policy_selectors:
        links = soup.select(selector)
        for link in links:
            href = link.get('href')
            text = link.get_text(strip=True)
            
            if href and len(text) > 5:  # Ensure meaningful text
                # Make full URL
                if href.startswith('/'):
                    full_url = "https://www.anthem.com" + href
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # Check if this is a policy link
                if is_actual_policy_link(href, text):
                    # Avoid duplicates
                    if not any(p['url'] == full_url for p in policy_links):
                        policy_links.append({
                            'url': full_url,
                            'title': text
                        })
                        logger.info("Found policy (selector)", title=text, url=full_url)
    
    # Strategy 2: If no direct links found, search more broadly
    if not policy_links:
        logger.info("No direct policy links found, searching more broadly")
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            href = link.get('href')
            text = link.get_text(strip=True)
            
            # Check if this is a medpolicies link
            if href and '/medpolicies/' in href.lower() and len(text) > 5:
                # Make full URL
                if href.startswith('/'):
                    full_url = "https://www.anthem.com" + href
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # Avoid duplicates
                if not any(p['url'] == full_url for p in policy_links):
                    policy_links.append({
                        'url': full_url,
                        'title': text
                    })
                    logger.info("Found policy (broad search)", title=text, url=full_url)
    
    if not policy_links:
        logger.warning("No policy links found")
        # Log first few links for debugging
        all_links = soup.find_all('a', href=True)[:10]
        for i, link in enumerate(all_links):
            logger.debug(
                "Sample link",
                index=i+1,
                href=link.get('href'),
                text=link.get_text(strip=True)[:50]
            )
        return []
    
    # Limit to first 10 policies
    first_10_policies = policy_links[:10]
    logger.info("Processing policies", count=len(first_10_policies))
    
    policy_results = []
    
    for i, policy in enumerate(first_10_policies, 1):
        try:
            logger.info(
                "Extracting policy",
                index=i,
                title=policy['title'],
                url=policy['url']
            )
            
            # Navigate to policy page
            driver.get(policy['url'])
            time.sleep(5)  # nosemgrep: arbitrary-sleep
            
            # Wait for content to load
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except:  # nosec B110
                pass
            
            # Extract content as markdown
            page_source = driver.page_source
            content = extract_clean_text_as_markdown(page_source)
            
            if content:
                # Extract policy identifier from URL
                policy_id = extract_policy_identifier(policy['url'])
                safe_id = sanitize_filename(policy_id)
                
                policy_results.append({
                    'url': policy['url'],
                    'content': content,
                    'title': policy['title'],
                    'filename': f"AnthemPolicy_{safe_id}.md",
                    'extraction_method': 'selenium_markdown'
                })
                
                logger.info(
                    "Policy extraction successful",
                    title=policy['title'],
                    char_count=len(content)
                )
            else:
                logger.warning(
                    "No content extracted",
                    title=policy['title']
                )
                
        except Exception as e:
            logger.error(
                "Error extracting policy",
                title=policy['title'],
                error=str(e),
                error_type=type(e).__name__
            )
            continue
    
    return policy_results


def search_anthem_policies(
    driver: webdriver.Chrome,
    search_url: str,
    service_code: str
) -> List[Dict[str, str]]:
    """
    Perform a search on Anthem's policy site and return policy results.
    
    Args:
        driver: Selenium WebDriver instance
        search_url: The search URL to use
        service_code: Service code being searched
        
    Returns:
        List of policy results with URLs and content
    """
    try:
        logger.info("Navigating to search URL", url=search_url)
        
        driver.get(search_url)
        time.sleep(5)  # nosemgrep: arbitrary-sleep
        
        # Wait for page to load and search results to appear
        try:
            WebDriverWait(driver, 20).until(
                lambda d: len(d.find_elements(By.TAG_NAME, "a")) > 5
            )
            # Additional wait for dynamic content
            time.sleep(8)  # nosemgrep: arbitrary-sleep
        except:
            # If waiting fails, still try to proceed
            time.sleep(10)  # nosemgrep: arbitrary-sleep
        
        # Parse search results
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        policy_results = get_first_10_anthem_policies(soup, driver, service_code)
        
        if policy_results:
            logger.info("Policies found", count=len(policy_results))
        else:
            logger.info("No policies found from this search")
        
        return policy_results
        
    except Exception as e:
        logger.error("Search failed", error=str(e), error_type=type(e).__name__)
        return []


def scrape_anthem_policies(
    service_code: str,
    state_code: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Scrape Anthem policies for a given service code.
    
    Tries two URL patterns:
    1. State-specific: https://www.anthem.com/provider/policies/clinical-guidelines/search/?cnslocale=en_US_{state}&q={code}
    2. State prefix: https://www.anthem.com/{state}/provider/policies/clinical-guidelines/search/?q={code}
    3. Generic fallback: https://www.anthem.com/provider/policies/clinical-guidelines/search/?q={code}
    
    Args:
        service_code: CPT/HCPCS code to search for
        state_code: Optional state code (e.g., "co", "ct", "ca")
        
    Returns:
        List of policy dictionaries with url, content, title, filename, extraction_method
    """
    logger.info(
        "Starting Anthem policy scrape",
        service_code=service_code,
        state_code=state_code
    )
    
    driver = None
    
    try:
        # Setup Chrome driver
        driver = setup_chrome_driver()
        
        policy_results = []
        
        # Try state-specific searches if state code provided
        if state_code:
            state_lower = state_code.lower()
            
            # Pattern 1: cnslocale parameter
            search_url_1 = (
                f"https://www.anthem.com/provider/policies/clinical-guidelines/search/"
                f"?cnslocale=en_US_{state_lower}&q={service_code}"
            )
            
            logger.info("Trying state-specific search (pattern 1)", url=search_url_1)
            policy_results = search_anthem_policies(driver, search_url_1, service_code)
            
            # Pattern 2: state prefix in URL
            if not policy_results:
                search_url_2 = (
                    f"https://www.anthem.com/{state_lower}/provider/policies/"
                    f"clinical-guidelines/search/?q={service_code}"
                )
                
                logger.info("Trying state-specific search (pattern 2)", url=search_url_2)
                policy_results = search_anthem_policies(driver, search_url_2, service_code)
        
        # Generic fallback (no state)
        if not policy_results:
            search_url_generic = (
                f"https://www.anthem.com/provider/policies/clinical-guidelines/search/"
                f"?q={service_code}"
            )
            
            logger.info("Trying generic search (fallback)", url=search_url_generic)
            policy_results = search_anthem_policies(driver, search_url_generic, service_code)
        
        if not policy_results:
            logger.warning("No policies found", service_code=service_code)
            return []
        
        logger.info(
            "Anthem scrape complete",
            service_code=service_code,
            policies_found=len(policy_results)
        )
        
        return policy_results
        
    except Exception as e:
        logger.error(
            "Error scraping Anthem policies",
            service_code=service_code,
            error=str(e),
            error_type=type(e).__name__
        )
        return []
        
    finally:
        if driver:
            driver.quit()
            logger.info("Chrome driver closed")
