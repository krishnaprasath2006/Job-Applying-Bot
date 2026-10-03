import math
import os
import sys
import time
from typing import List
from urllib.parse import quote_plus, unquote_plus

import config
import constants

sys.stdout.reconfigure(encoding='utf-8')

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

# Well known install locations of the Chromium based browsers. Used only to give
# a clear error message (or to fall back to the other browser) instead of the
# cryptic "cannot find Chrome binary" from chromedriver.
CHROME_BINARY_LOCATIONS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
EDGE_BINARY_LOCATIONS = [
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

def browserBinaryInstalled(browser: str) -> bool:
    """True if the requested Chromium based browser is installed on this machine."""
    locations = EDGE_BINARY_LOCATIONS if browser.strip().lower() == "edge" else CHROME_BINARY_LOCATIONS
    return any(os.path.exists(path) for path in locations)


def applyChromiumOptions(options) -> None:
    """Apply the arguments and profile/incognito settings shared by Chrome and Edge."""
    options.add_argument('--no-sandbox')
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-extensions")
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-dev-shm-usage')
    if(config.headless):
        options.add_argument("--headless")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option('useAutomationExtension', False)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    if(len(config.chromeProfilePath)>0):
        # Handle both Windows (\) and Unix (/) path separators
        # Normalize path separators to handle mixed separators
        normalized_path = config.chromeProfilePath.replace('\\', os.sep).replace('/', os.sep)
        
        # Find the last path separator (works for both Windows and Unix)
        last_sep_index = normalized_path.rfind(os.sep)
        
        if last_sep_index != -1:
            initialPath = normalized_path[:last_sep_index]
            profileDir = normalized_path[last_sep_index + 1:]
        else:
            # If no separator found, treat entire path as profile directory
            # and use parent directory as user-data-dir
            initialPath = os.path.dirname(normalized_path)
            profileDir = os.path.basename(normalized_path)
        
        options.add_argument('--user-data-dir=' + initialPath)
        options.add_argument("--profile-directory=" + profileDir)
    else:
        options.add_argument("--incognito")
    return options

def chromeBrowserOptions():
    options = webdriver.ChromeOptions()
    return applyChromiumOptions(options)

def edgeBrowserOptions():
    options = webdriver.EdgeOptions()
    return applyChromiumOptions(options)


def _launchDriver(browser: str):
    """Start one specific browser and return its WebDriver."""
    if browser == "edge":
        # Selenium 4.6+ ships Selenium Manager, which downloads the matching
        # msedgedriver automatically - no extra package needed.
        return webdriver.Edge(options=edgeBrowserOptions())

    # Chrome needs the explicit path because of the WinError 193 issue.
    chrome_install = ChromeDriverManager().install()
    folder = os.path.dirname(chrome_install)
    chromedriver_path = os.path.join(folder, "chromedriver.exe")
    if os.path.exists(chromedriver_path):
        return webdriver.Chrome(service=ChromeService(chromedriver_path), options=chromeBrowserOptions())
    return webdriver.Chrome(service=ChromeService(chrome_install), options=chromeBrowserOptions())


def createDriver():
    """Create the WebDriver for config.browser, falling back to the other Chromium browser.

    Chrome is tried first by default. If Chrome is not installed (or fails to
    start) the bot uses Edge, which speaks the same DevTools protocol, and says
    so loudly in the console.
    """
    requested = (config.browser[0] if config.browser else "Chrome").strip().lower()
    if requested not in ("chrome", "edge"):
        prYellow(f"⚠️ Warning: Unknown browser '{requested}' in config, using Chrome.")
        requested = "chrome"

    candidates = [requested, "edge" if requested == "chrome" else "chrome"]
    problems = []

    for browser in candidates:
        if not browserBinaryInstalled(browser):
            problems.append(f"{browser}: not installed on this machine")
            continue
        try:
            driver = _launchDriver(browser)
            if browser != requested:
                prYellow(f"⚠️ Warning: {requested.capitalize()} is unavailable, running on {browser.capitalize()} instead.")
            return driver
        except Exception as e:
            problems.append(f"{browser}: {type(e).__name__}: {str(e).splitlines()[0][:140]}")

    raise RuntimeError(
        "Could not start a browser. Tried:\n  - " + "\n  - ".join(problems)
    )


def validateConfig() -> List[str]:
    """Return a list of human readable configuration problems (empty list = all good)."""
    problems: List[str] = []

    if config.credentialsMissing():
        problems.append(
            "LinkedIn email/password are empty. Put them in the .env file next to linkedin.py "
            "(copy .env.example -> .env) - do NOT hardcode them in config.py."
        )
    if not config.location:
        problems.append("config.location is empty - there is nothing to search.")
    if not config.keywords:
        problems.append("config.keywords is empty - there is nothing to search.")
    if not config.experienceLevels:
        problems.append("config.experienceLevels is empty - the experience filter will be skipped.")
    if not config.datePosted:
        problems.append("config.datePosted is empty - pick one of 'Any Time', 'Past Month', 'Past Week', 'Past 24 hours'.")
    if not config.sort:
        problems.append("config.sort is empty - the jobs will not be sorted by recent/relevant.")
    if not config.salary:
        problems.append("config.salary is empty - use [\"\"] to apply no salary filter.")
    if config.maxApplicationsPerRun < 0:
        problems.append("config.maxApplicationsPerRun cannot be negative. Use 0 for no limit.")

    if config.displayWarnings is False and config.dryRun is True:
        problems.append("Tip: config.displayWarnings = True helps you see what the bot skipped and why.")

    return problems


def printRunBanner() -> None:
    """Print the safety state of this run before the browser opens."""
    if config.dryRun:
        prYellow("🧪 DRY RUN is ON - the bot will NOT click 'Submit application' on any job.")
    else:
        prRed("🚨 REAL RUN - the bot WILL submit real applications. Set config.dryRun = True to stop that.")
    cap = "no limit" if not config.maxApplicationsPerRun else str(config.maxApplicationsPerRun)
    prYellow(f"📌 Max applications this run: {cap} (dry-run candidates are counted too).")
    prYellow(f"🔎 Searching {len(config.keywords)} keyword(s) x {len(config.location)} location(s).")

def prRed(prt: str) -> None:
    print(f"\033[91m{prt}\033[00m")

def prGreen(prt: str) -> None:
    print(f"\033[92m{prt}\033[00m")

def prYellow(prt: str) -> None:
    print(f"\033[93m{prt}\033[00m")

def getUrlDataFile() -> List[str]:
    """Read generated job search URLs from the data file.

    Returns a list of URL strings with whitespace stripped.
    Returns an empty list if the file is missing.
    """
    urlData: List[str] = []
    try:
        with open('data/urlData.txt', 'r') as file:
            urlData = [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        text = "FileNotFound:urlData.txt file is not found. Please run ./data folder exists and check config.py values of yours. Then run the bot again"
        prRed(text)
    return urlData

def jobsToPages(numOfJobs: str) -> int:
  number_of_pages = 1

  if (' ' in numOfJobs):
    spaceIndex = numOfJobs.index(' ')
    totalJobs = (numOfJobs[0:spaceIndex])
    totalJobs_int = int(totalJobs.replace(',', ''))
    number_of_pages = math.ceil(totalJobs_int/constants.jobsPerPage)
    if (number_of_pages > 40 ): number_of_pages = 40

  else:
      number_of_pages = int(numOfJobs)

  return number_of_pages

def urlToKeywords(url: str) -> List[str]:
    keywordUrl = url[url.index("keywords=")+9:]
    keyword = unquote_plus(keywordUrl[0:keywordUrl.index("&") ] )
    locationUrl =  url[url.index("location=")+9:]
    location = unquote_plus(locationUrl[0:locationUrl.index("&") ] )
    return [keyword, location]

def writeResults(text: str) -> None:
    """Append one result line to today's data file, creating the header if needed.

    The old version rewrote the whole file on every line and dropped any line
    containing "----", which silently deleted the session summary. Appending is
    both faster and keeps the full history.
    """
    timeStr = time.strftime("%Y%m%d")
    fileName = "data/Applied Jobs DATA - " + timeStr + ".txt"
    try:
        if not os.path.exists("data"):
            os.makedirs("data", exist_ok=True)

        isNewFile = (not os.path.exists(fileName)) or os.path.getsize(fileName) == 0
        with open(fileName, 'a', encoding="utf-8") as f:
            if isNewFile:
                f.write("---- Applied Jobs Data ---- created at: " + timeStr + "\n")
                f.write("---- Number | Job Title | Company | Location | Work Place | Posted Date | Applications | Result \n")
            f.write(text + "\n")
    except Exception as e:
        prRed("❌ Could not write to the data file: " + str(e)[:100])

def printInfoMes(bot: str) -> None:
    prYellow("ℹ️ " +bot+ " is starting soon... ")


def printSessionSummary(
    count_jobs: int,
    count_applied: int,
    count_blacklisted: int,
    count_already_applied: int,
    count_cannot_apply: int,
    duration_sec: float,
):
    """Print and write a session summary to the data file."""
    duration_min = round(duration_sec / 60, 1)
    prGreen("\n" + "=" * 60)
    prGreen("📊 SESSION SUMMARY")
    prGreen("=" * 60)
    prGreen(f"   Jobs processed:     {count_jobs}")
    prGreen(f"   ✅ Applied:         {count_applied}")
    prGreen(f"   🤬 Blacklisted:     {count_blacklisted}")
    prGreen(f"   🥳 Already applied: {count_already_applied}")
    prGreen(f"   🥵 Could not apply: {count_cannot_apply}")
    prGreen(f"   ⏱ Duration:         {duration_min} minute(s)")
    prGreen("=" * 60 + "\n")

    time_str = time.strftime("%Y%m%d")
    file_name = "Applied Jobs DATA - " + time_str + ".txt"
    summary_lines = [
        "",
        "---- Session Summary ----",
        f"Jobs processed: {count_jobs} | Applied: {count_applied} | Blacklisted: {count_blacklisted} | Already applied: {count_already_applied} | Could not apply: {count_cannot_apply} | Duration: {duration_min} min",
    ]
    try:
        data_dir = "data"
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        file_path = os.path.join(data_dir, file_name)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")
    except Exception as e:
        prRed("❌ Could not write session summary to file: " + str(e)[:80])

def donate() -> None:
    prYellow('If you like the project, please support me so that i can make more such projects, thanks!')

class LinkedinUrlGenerate:
    def generateUrlLinks(self) -> List[str]:
        path: List[str] = []
        for location in config.location:
            for keyword in config.keywords:
                    # Keywords can contain spaces/special characters, so encode them.
                    url = constants.linkJobUrl + "?f_AL=true&keywords=" +quote_plus(keyword)+self.jobType()+self.remote()+self.checkJobLocation(location)+self.jobExp()+self.datePosted()+self.salary()+self.sortBy()
                    path.append(url)
        return path

    def checkJobLocation(self, job: str) -> str:
        jobLoc = "&location=" +job
        match job.casefold():
            case "asia":
                jobLoc += "&geoId=102393603"
            case "europe":
                jobLoc += "&geoId=100506914"
            case "northamerica":
                jobLoc += "&geoId=102221843&"
            case "southamerica":
                jobLoc +=  "&geoId=104514572"
            case "australia":
                jobLoc +=  "&geoId=101452733"
            case "africa":
                jobLoc += "&geoId=103537801"

        return jobLoc

    def jobExp(self) -> str:
        jobtExpArray = config.experienceLevels
        firstJobExp = jobtExpArray[0]
        jobExp = ""
        match firstJobExp:
            case "Internship":
                jobExp = "&f_E=1"
            case "Entry level":
                jobExp = "&f_E=2"
            case "Associate":
                jobExp = "&f_E=3"
            case "Mid-Senior level":
                jobExp = "&f_E=4"
            case "Director":
                jobExp = "&f_E=5"
            case "Executive":
                jobExp = "&f_E=6"
        for index in range (1,len(jobtExpArray)):
            match jobtExpArray[index]:
                case "Internship":
                    jobExp += "%2C1"
                case "Entry level":
                    jobExp +="%2C2"
                case "Associate":
                    jobExp +="%2C3"
                case "Mid-Senior level":
                    jobExp += "%2C4"
                case "Director":
                    jobExp += "%2C5"
                case "Executive":
                    jobExp  +="%2C6"

        return jobExp

    def datePosted(self) -> str:
        datePosted = ""
        match config.datePosted[0]:
            case "Any Time":
                datePosted = ""
            case "Past Month":
                datePosted = "&f_TPR=r2592000&"
            case "Past Week":
                datePosted = "&f_TPR=r604800&"
            case "Past 24 hours":
                datePosted = "&f_TPR=r86400&"
        return datePosted

    def jobType(self) -> str:
        jobTypeArray = config.jobType
        firstjobType = jobTypeArray[0]
        jobType = ""
        match firstjobType:
            case "Full-time":
                jobType = "&f_JT=F"
            case "Part-time":
                jobType = "&f_JT=P"
            case "Contract":
                jobType = "&f_JT=C"
            case "Temporary":
                jobType = "&f_JT=T"
            case "Volunteer":
                jobType = "&f_JT=V"
            case "Intership":
                jobType = "&f_JT=I"
            case "Other":
                jobType = "&f_JT=O"
        for index in range (1,len(jobTypeArray)):
            match jobTypeArray[index]:
                case "Full-time":
                    jobType += "%2CF"
                case "Part-time":
                    jobType +="%2CP"
                case "Contract":
                    jobType +="%2CC"
                case "Temporary":
                    jobType += "%2CT"
                case "Volunteer":
                    jobType += "%2CV"
                # "Intership" is the original typo, "Internship" is the correct spelling.
                case "Intership" | "Internship":
                    jobType  +="%2CI"
                case "Other":
                    jobType  +="%2CO"
        jobType += "&"
        return jobType

    def remote(self) -> str:
        remoteArray = config.remote
        firstJobRemote = remoteArray[0]
        jobRemote = ""
        match firstJobRemote:
            case "On-site":
                jobRemote = "f_WT=1"
            case "Remote":
                jobRemote = "f_WT=2"
            case "Hybrid":
                jobRemote = "f_WT=3"
        for index in range (1,len(remoteArray)):
            match remoteArray[index]:
                case "On-site":
                    jobRemote += "%2C1"
                case "Remote":
                    jobRemote += "%2C2"
                case "Hybrid":
                    jobRemote += "%2C3"

        return jobRemote

    def salary(self) -> str:
        salary = ""
        match config.salary[0]:
            case "$40,000+":
                salary = "f_SB2=1&"
            case "$60,000+":
                salary = "f_SB2=2&"
            case "$80,000+":
                salary = "f_SB2=3&"
            case "$100,000+":
                salary = "f_SB2=4&"
            case "$120,000+":
                salary = "f_SB2=5&"
            case "$140,000+":
                salary = "f_SB2=6&"
            case "$160,000+":
                salary = "f_SB2=7&"    
            case "$180,000+":
                salary = "f_SB2=8&"    
            case "$200,000+":
                salary = "f_SB2=9&"                  
        return salary

    def sortBy(self) -> str:
        sortBy = ""
        match config.sort[0]:
            case "Recent":
                sortBy = "sortBy=DD"
            case "Relevent":
                sortBy = "sortBy=R"                
        return sortBy
