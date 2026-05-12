# Security

## Reporting Security Issues

If you discover a potential security issue in this project, please report it to AWS Security via our [vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/).

## Known Accepted Risks

### pypdf DoS Vulnerabilities (WARNING)
The `pypdf` library has several known DoS-type vulnerabilities related to malformed PDF streams (LZWDecode, FlateDecode, RunLengthDecode, ASCIIHexDecode). These can cause high memory usage or long runtimes when processing specially crafted PDFs. In this solution, pypdf processes payor policy PDFs from trusted sources (payor websites), so the risk of encountering malicious PDFs is low. If you deploy this in an environment where untrusted PDFs may be processed, consider adding PDF size limits and processing timeouts.

### requests .netrc Credential Leak (WARNING)
The `requests` library (2.32.3, latest) has a known vulnerability where credentials from `.netrc` files could leak via malicious redirect URLs. This solution uses `requests` for scraping payor policy websites over HTTPS. The risk is mitigated by the fact that Lambda execution environments do not have `.netrc` files.

### Frontend Transitive Dependencies (WARNING)
Several transitive dependencies of `react-scripts` (postcss, webpack-dev-server) have known vulnerabilities. These are development-time dependencies and are not included in the production build. The `package.json` includes `overrides` to force safer versions where possible.

### time.sleep() in Scrapers
Web scrapers use intentional `time.sleep()` calls for rate-limiting to avoid being blocked by payor websites. These are not security issues.
