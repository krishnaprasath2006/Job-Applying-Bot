# CURRENT SYSTEM AUDIT

**Audit date:** 2026-09-30
**Audited commit:** `4717b55` (local checkpoint on top of upstream `70fe748`)
**Auditor scope:** full static read of every source file, plus live runtime
verification of the browser, config, and data layers on the target machine
(Windows 11, Python 3.11.8, Microsoft Edge 154).
**Code modified during this audit:** none. This document is observation only.

---

## 1. WHAT THIS PROJECT IS

`EasyApplyJobsBot` is a single-purpose Selenium script that:

1. Opens a Chromium browser
2. Logs into LinkedIn with stored credentials
3. Builds LinkedIn job-search URLs from a flat `config.py`
4. Walks paginated search results
5. Opens each job, reads title/company/location
6. Clicks "Easy Apply"
7. Picks a resume
8. Optionally fills a phone number
9. Clicks "Submit application"
10. Appends a text line to `data/Applied Jobs DATA - YYYYMMDD.txt`

There is no database, no AI, no job memory, no deduplication, no state
machine, no tests, and no user interface beyond `print()`.

The upstream project also sells a "Pro" version. Roughly 20 config settings in
`config.py` are labelled `PRO FEATURE` and are **not implemented anywhere in the
open-source code**. They are documented in the README's free-vs-pro table.

---

## 2. CURRENT FILE STRUCTURE

```
EasyApplyJobsBot/
├── .dockerignore                 (512 B)   excludes data/, cookies/, .git
├── .env                          (local)    LinkedIn credentials - git-ignored
├── .env.example                  (local)    empty template - tracked
├── .gitignore                    (3.5 KB)   Python template; .env at line 123
├── .kilo/worktrees/…             (local)    agent tool scratch worktree, not project code
├── Dockerfile                    (1.8 KB)   Linux + Google Chrome, runs linkedin.py
├── LICENSE                       (15 KB)    open source license
├── additionalQuestions.yaml      (48 KB)    264 hardcoded answers, tracked in git
├── config.py                     (166 L)    ALL settings + credentials
├── constants.py                  (23 L)     URLs, speeds, selector literals
├── docker-compose.yml            (833 B)    volume mounts
├── linkedin.py                   (558 L)    THE application
├── requirements.txt              (4 L)      pinned-ish deps
├── requirements.yaml             (3 L)      unpinned, unpkg-only (see §11)
├── utils.py                      (448 L)    browser options, URL builder, writers
└── README.md                     (343 L)    upstream docs, heavily sales-oriented
```

**Notably absent:** no `tests/`, no `docs/`, no `data/`, no `cookies/` in the
repo (both are created at runtime), no `.github/` CI, no `pyproject.toml`,
no lint config, no type checker config.

### 2.1 File-by-file responsibility

| File | Lines | Responsibility | Notes |
|---|---|---|---|
| `linkedin.py` | 558 | Browser lifecycle, login, session cookies, URL generation trigger, the whole search/apply loop, resume selection, phone filling, result writing | Single class `Linkedin` with 15 methods. Contains **all** Selenium, **all** control flow, **all** output. |
| `utils.py` | 448 | `chromeBrowserOptions()`, `edgeBrowserOptions()`, `createDriver()`, `validateConfig()`, `printRunBanner()`, `prRed/prGreen/prYellow`, `getUrlDataFile()`, `jobsToPages()`, `urlToKeywords()`, `writeResults()`, `printSessionSummary()`, `donate()`, `LinkedinUrlGenerate` (URL builder) | Mixed concerns: browser setup + URL building + console colors + file IO. |
| `config.py` | 166 | Every tunable as a bare module-level variable. Loads `.env` for credentials. | No schema, no validation at import, no types. ~20 dead PRO settings. |
| `constants.py` | 23 | Base URLs, `jobsPerPage=25`, speed presets (`fast/medium/slow`, active=`slow`), and 4 selector literals | Contains a `testJobUrl` hardcode with a stale `geoId`. |
| `additionalQuestions.yaml` | 48 KB | 165 `inputField`, 48 `radio`, 51 `dropdown` answers belonging to the **upstream author's** personal history (Poland, Canada, katowice) | Tracked in git. **Only one key is ever read by free code**: `inputField."Phone Number"`. |
| `requirements.txt` | 4 | `selenium>=4.0.0`, `webdriver_manager>=3.8.0`, `selenium-stealth>=1.0.0`, `pyyaml>=5.1` | Lower bounds only, no upper bounds. |
| `requirements.yaml` | 3 | `selenium`, `webdriver_manager`, `selenium-stealth` | **Missing `pyyaml`.** Divergent duplicate of requirements.txt. |
| `Dockerfile` | 78 | Debian slim + system Chrome deps + `google-chrome-stable` | Linux-only. Cannot run on the user's Windows host. |
| `docker-compose.yml` | 25 | Mounts `data/`, `cookies/`, `config.py`, `additionalQuestions.yaml` | `config.py` bind-mount means config edits never require rebuild. |

---

## 3. CURRENT EXECUTION FLOW

Entry point: `linkedin.py:509 main()`.

```
main()                                              linkedin.py:509
 ├─ utils.printRunBanner()                          [added in checkpoint]
 ├─ utils.validateConfig() -> sys.exit(1) on error  [added in checkpoint]
 ├─ Linkedin()                                      linkedin.py:28
 │   ├─ utils.prYellow banner
 │   ├─ utils.createDriver()                        utils.py:118
 │   │   ├─ webdriver_manager -> chromedriver.exe   (Chrome only)
 │   │   └─ Selenium Manager -> msedgedriver       (Edge; automatic)
 │   ├─ stealth(driver) if selenium_stealth present linkedin.py:47
 │   ├─ cookies_path = cookies/md5(config.email).pkl
 │   ├─ driver.get("https://www.linkedin.com")
 │   ├─ loadCookies()   -> pickle.load -> delete_all_cookies -> add_cookie each
 │   └─ isLoggedIn()    -> get(/feed), look for //*[@id="ember14"]
 │        └─ if False:
 │             ├─ if credentialsMissing(): quit + sys.exit(1)   [added]
 │             ├─ get(/login)
 │             ├─ type #username, type #password, click button[type=submit]
 │             ├─ time.sleep(30)          <-- fixed 30 s wait
 │             └─ saveCookies() -> pickle.dump
 └─ linkJobApply()                                  linkedin.py:118
     ├─ generateUrls() -> write data/urlData.txt    linkedin.py:110
     ├─ urlData = utils.getUrlDataFile()   (List[str])
     ├─ for url in urlData:                         10 search URLs
     │   ├─ driver.get(url); sleep(random 1..botSpeed)
     │   ├─ totalJobs = //small .text               linkedin.py:139
     │   │    └─ on failure: log "No jobs found", continue
     │   ├─ totalPages = utils.jobsToPages(totalJobs)   capped at 40
     │   └─ for page in range(totalPages):
     │        ├─ url += "&start=" + page*25
     │        ├─ find //li[@data-occludable-job-id]  -> offerIds
     │        ├─ re-find, drop offers whose text contains "Applied"
     │        └─ for jobID in offerIds:
     │             ├─ driver.get(/jobs/view/<id>)
     │             ├─ jobProperties = getJobProperties(count)   5 s sleep inside
     │             ├─ if "blacklisted" in jobProperties: log + skip
     │             ├─ easyApplyButton = easyApplyButton()      sleep inside
     │             ├─ if button:
     │             │   ├─ click
     │             │   ├─ try click "Continue to next step" (issue #72 workaround)
     │             │   ├─ try:
     │             │   │   chooseResume(); fillPhoneNumber()
     │             │   │   if config.dryRun: log "DRY RUN"      # NO SUBMIT
     │             │   │   else: submitApplication(); countApplied++
     │             │   ├─ except:  <-- swallows everything above
     │             │   │   ├─ try: fillPhone(); click Continue; chooseResume()
     │             │   │   │      read //html/body/div[3]/…/span -> "NN%"
     │             │   │   │      if dryRun: log "multi-step DRY RUN"
     │             │   │   │      else: applyProcess(percentage, url)
     │             │   │   └─ except: countCannotApply++; log "Cannot apply"
     │             └─ else: countAlreadyApplied++; log
     ├─ utils.printSessionSummary(...)
     └─ utils.donate()
```

**Application step-count derivation** — `applyProcess(percentage, offerPage)`,
`linkedin.py:481`:

```python
applyPages = math.floor(100 / percentage) - 2
for pages in range(applyPages):
    self.driver.find_element(By.CSS_SELECTOR, "button[aria-label='Continue to next step']").click()
```

The loop count is **inferred from a progress percentage scraped out of a
positional XPath**, then used to decide how many times to click Continue. This
is the single most fragile control-flow construct in the codebase. See §12.1.

---

## 4. CURRENT DEPENDENCIES

Declared in `requirements.txt`:

| Package | Declared | Actually installed on target machine |
|---|---|---|
| `selenium` | `>=4.0.0` | 4.49.0 |
| `webdriver_manager` | `>=3.8.0` | 4.1.2 |
| `selenium-stealth` | `>=1.0.0` | 1.0.6 |
| `pyyaml` | `>=5.1` | 6.0.3 |
| `python-dotenv` | **not declared** | 1.2.3 (present transitively / pre-installed) |

`config.py:3-8` imports `dotenv` inside a `try/except ImportError`, so
`python-dotenv` is a **soft** dependency: without it, `config.email` and
`config.password` are always empty and login silently cannot proceed.
This must be added to `requirements.txt` before the upgrade.

Standard library used for persistence: `pickle` (cookies), `json` (unused),
`math`, `random`, `time`, `os`, `hashlib`, `sys`.

**No dependency is used for:** PDF parsing, DOCX parsing, embeddings, vector
storage, database access, HTTP API, UI, testing, logging, or schema validation.
Every one of those is net-new work.

---

## 5. BROWSER AUTOMATION ARCHITECTURE

### 5.1 How the browser is created

Before the checkpoint commit, `linkedin.py.__init__` inlined driver creation
with a `ChromeDriverManager()` call and a `WinError 193` workaround. The
checkpoint moved this to `utils.createDriver()` (`utils.py:118`) which:

1. Reads `config.browser[0]`
2. Checks the binary against hardcoded Windows paths
   (`utils.CHROME_BINARY_LOCATIONS`, `utils.EDGE_BINARY_LOCATIONS`)
3. Launches Chrome via explicit `chromedriver.exe` path, **or** Edge via
   Selenium Manager (auto-downloads `msedgedriver`)
4. Falls back to the other browser if the requested one is missing or fails
5. Raises a `RuntimeError` listing every attempt if both fail

**Verified at runtime:** `config.browser = ["Edge"]` → `MicrosoftEdge 154.0.4258.37`
launches, loads `https://www.linkedin.com/jobs/search/...`, returns a 36-char
title, quits cleanly.

### 5.2 Anti-detection surface

`utils.applyChromiumOptions()` (`utils.py:38`) sets:
`--no-sandbox`, `--ignore-certificate-errors`, `--disable-extensions`,
`--disable-gpu`, `--disable-dev-shm-usage`, `--start-maximized`,
`--disable-blink-features=AutomationControlled`,
`excludeSwitches=["enable-automation"]`, `useAutomationExtension=False`.

`linkedin.py:47` additionally applies `selenium_stealth.stealth()` with a
hardcoded vendor/platform/webgl triple (`"Win32"`, `"Intel Iris OpenGL Engine"`).

**Audit note:** this code exists in upstream and is out of scope for the current
task, but §27 of the target design explicitly prohibits evasion techniques.
This is flagged as a decision point, not silently changed. See §16.3.

### 5.3 Waits

**18 `time.sleep()` calls in `linkedin.py`, 0 `WebDriverWait` usages.** Fixed
sleeps: 2 s between login fields, **30 s after login click**, 5 s inside
`getJobProperties`, 1–5 s randomised (`random.uniform(1, botSpeed)`) between
navigations, 0.5 s per phone field.

There is no `WebDriverWait`, no `expected_conditions`, no implicit-wait tuning.
Every wait is a guess. This is simultaneously too slow (fixed sleeps when the
page is instant) and too fragile (no wait when the page is slow).

---

## 6. AUTHENTICATION AND SESSION HANDLING

### 6.1 Credential path (post-checkpoint)

```
.env  →  python-dotenv  →  os.getenv  →  config.email / config.password
```

`.env` is git-ignored (`.gitignore:123`). `.env.example` is tracked with empty
values. Verified: `git ls-files` does not list `.env`.

**Upstream originally hardcoded** `email = "YourLinkedin@UserEmail.com"` and
`password = "YourLinkedinPassword"` at `config.py:7-8` and the README instructed
users to type real credentials into those lines. That is fixed.

### 6.2 Session cookies

`linkedin.py:52` → `cookies/md5(email).pkl`, `pickle` serialized.

- `loadCookies()` — `pickle.load` then `delete_all_cookies()` then `add_cookie()`
  for each. **No try/except.** A corrupt or foreign-format pickle file crashes
  the process at startup.
- `saveCookies()` — wrapped in `try/except`, silently continues on failure
  unless `config.displayWarnings`.
- Cookies are **plaintext pickle**, unencrypted, on disk, keyed only by an MD5
  of the email. Anyone with filesystem read access has a live LinkedIn session.
- `cookies/` is in `.dockerignore` and `docker-compose.yml` but is **not in
  `.gitignore`** — it is currently untracked only because it does not exist yet.
  Running the bot once creates it in a git-visible directory.

### 6.3 Login detection

`isLoggedIn()` (`linkedin.py:99`) navigates to `/feed` and looks for a single
magic element `//*[@id="ember14"]`. This is a hashed Ember.js component ID
with no semantic meaning. It is not a "logged in" signal — it is "some specific
internal component rendered".

There is no handling for: 2FA, CAPTCHA, checkpoint/challenge pages, session
expiry mid-run, or "account temporarily restricted". See §13.

---

## 7. CURRENT FILTERS

All filters live in `config.py` and are compiled into LinkedIn URL query
parameters by `utils.LinkedinUrlGenerate` (`utils.py:249`).

| Config key | LinkedIn param | Notes |
|---|---|---|
| `location` | `&location=` + optional `&geoId=` | `geoId` only for the 6 continent names; any other string passes through bare |
| `keywords` | `&keywords=` | URL-encoded via `quote_plus` (checkpoint fix) |
| `jobType` | `f_JT=` | `match` statement; `Internship` was silently dropped due to an `Intership` typo (checkpoint fix) |
| `remote` | `f_WT=` | |
| `experienceLevels` | `f_E=` | |
| `datePosted` | `f_TPR=` | single value only |
| `salary` | `f_SB2=` | single value only; USD buckets |
| `sort` | `sortBy=` | `DD` or `R` |
| `f_AL` | hardcoded `true` | Easy Apply only, always on, not configurable |

**Post-blacklist** filters (applied after opening each job, in
`getJobProperties`, `linkedin.py:331`):

- `blackListTitles` — substring match against the job title
- `blacklistCompanies` — substring match against the job title
  (**bug**: should match the company; fixed in checkpoint to match `jobDetail`)

**Dead PRO filters** — these 14 settings are read by nothing in the OSS code:
`onlyApplyCompanies`, `onlyApplyTitles`, `blockHiringMember`,
`onlyApplyHiringMember`, `onlyApplyMaxApplications`,
`onlyApplyMinApplications`, `onlyApplyJobDescription`, `blockJobDescription`,
`onlyAppyMimEmployee`, `onlyApplyLinkedinRecommending`,
`onlyApplySkilledBages`, `saveBeforeApply`, `messageToHiringManager`,
`listNonEasyApplyJobsUrl`, `defaultRadioOption`, `answerAllCheckboxes`.

**No filter exists for:** job seniority in the title, years-of-experience
mentions in the description, company size, industry, spam/quality signals, or
cross-run duplicate suppression.

---

## 8. JOB DISCOVERY LOGIC

`utils.LinkedinUrlGenerate.generateUrlLinks()` (`utils.py:249`) builds
`len(config.location) × len(config.keywords)` URLs as a cartesian product.
Current config = 10 keywords × 1 location = **10 URLs**.

`linkedin.linkJobApply()` then, per URL:

1. `driver.get(url)`, sleep
2. Read total job count from `//small` — the **first `<small>` element on the
   entire page**, not a scoped one. Any other `<small>` on the page wins.
3. `utils.jobsToPages()` (`utils.py:76`) parses "1,234 " → `ceil(1234/25)`,
   hard-capped at 40 pages
4. For each page, append `&start=<n>` and reload
5. Collect `//li[@data-occludable-job-id]`, parse the trailing integer

**Verified limitation:** when logged out, LinkedIn renders a completely
different DOM. A live check found `0` elements matching
`//li[@data-occludable-job-id]` while `180` `job-search-card` nodes and 61
`/jobs/view/` links existed. **Discovery only works when logged in.** This was
confirmed empirically, not assumed.

---

## 9. JOB PARSING LOGIC

`getJobProperties(count)` (`linkedin.py:331`) returns one formatted string:

| Field | Source | Fragility |
|---|---|---|
| job title | `//h1[contains(@class,'job-title')]`.`innerHTML` | class name |
| company + meta | `//div[contains(@class,'job-details-jobs')]//div`.text, `·`→`\|` | class name; whole block collapsed to one string |
| workplace type | `//span[contains(@class,'ui-label ui-label--accent-3 text-body-small')]//span[contains(@aria-hidden,'true')]` | 4 chained class names |

Output format: `"<n> | <title> | <detail><location>"`.

**The full job description is never read.** There is no JD text extraction
anywhere in the codebase. The description exists only as an untargeted
`jobDetail` string used for company blacklisting. This is the single biggest
functional gap: no requirement extraction, no matching, no ATS, no
cover-letter grounding is possible without it.

---

## 10. RESUME AND QUESTION-ANSWER LOGIC

### 10.1 Resume

`chooseResume()` (`linkedin.py:317`):

```python
self.driver.find_element(By.CLASS_NAME, "jobs-document-upload__title--is-required")
resumes = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'ui-attachment--pdf')]")
if len(resumes) == 1 and resumes[0].get_attribute("aria-label") == "Select this resume":
    resumes[0].click()
elif len(resumes) > 1 and resumes[config.preferredCv-1].get_attribute("aria-label") == "Select this resume":
    resumes[config.preferredCv-1].click()
```

- Selects by **positional index only** (`config.preferredCv`). No matching
  against the job.
- The `find_element` on line 319 is a **presence probe whose result is
  discarded** — it exists only to trigger the `except: pass`. If the probe
  fails, the whole function silently does nothing and the application is
  submitted with whatever resume LinkedIn pre-selected.
- The final `elif (type(len(resumes)) != int)` is dead code: `len()` always
  returns `int`, so this branch is unreachable.
- Wrapped entirely in `try/except: pass`.

### 10.2 Phone number

`fillPhoneNumber()` (`linkedin.py:384`) — the **only** consumer of
`additionalQuestions.yaml` in the entire free codebase.

- Source order: `config.Phone` (env `APPLICANT_PHONE`) → YAML
  `inputField."Phone Number"`
- Current YAML value: `1234567890` with `Phone Country Code: Canada (+1)` —
  the **upstream author's fake data**
- 7 CSS selectors + 4 case-normalized XPath selectors
- Fills only if `is_displayed()` and `current_value == ""`
- Wrapped in `try/except` that only logs when `displayWarnings`

### 10.3 Everything else

**There is no question-answering engine.** No radio button handling, no
dropdown handling, no text-field answering, no unknown-question capture, no
`data/review_queue/`, no `outputSkippedQuestions` implementation. These are
Pro-only, per the README's own feature table (rows marked ❌ for Free).

The 264 answers in `additionalQuestions.yaml` are therefore **263/264 dead
weight** in the free version, and all of them describe a person who is not the
user (Poland-based, Canadian phone, Polish city names).

---

## 11. CURRENT DATA PERSISTENCE AND OUTPUT

### 11.1 Files

| Path | Written by | Contents |
|---|---|---|
| `data/urlData.txt` | `generateUrls()` | one search URL per line |
| `data/Applied Jobs DATA - YYYYMMDD.txt` | `writeResults()` + `printSessionSummary()` | header, one line per job, session summary |
| `cookies/<md5>.pkl` | `saveCookies()` | pickled session cookies |

### 11.2 The rewrite bug (fixed in checkpoint)

Original `writeResults()` read the whole file, **dropped every line containing
`"----"`**, rewrote the file, and appended the new line. Consequence: the
`---- Session Summary ----` block written by `printSessionSummary()` was erased
by the first result line of the next run. The checkpoint replaced it with a
plain append that writes the header only when the file is new/empty.

**Verified after fix:** a line, then a session summary, then another line — all
three survive.

### 11.3 What is missing

No `jobs` table. No memory of jobs seen. No application records. No answer
history. No question cache. No embeddings. No migration story. No export
beyond one flat text file. No structured status. "Applied" is inferred from a
substring match on card text, not stored.

---

## 12. FAILURE MODES AND TECHNICAL DEBT

### 12.1 Critical

| # | Issue | Location | Effect |
|---|---|---|---|
| C1 | **Step count guessed from a progress percentage** via a positional XPath | `linkedin.py:481` `math.floor(100/percentage) - 2` | If `percentage` is stale or misread, the loop clicks Continue the wrong number of times. On the last form page "Continue" becomes "Review your application" → exception → swallowed → counted as "Cannot apply", **or worse**, the loop under-counts and proceeds to submit on an incomplete form. |
| C2 | **Submit outcome never verified** | `linkedin.py:315` | The code clicks Submit, sleeps 1–5 s, and writes "🥳 Just Applied". No confirmation is read. A CAPTCHA, a validation error, or a rate-limit wall produces a **false success record**. |
| C3 | **Broad `except` around the entire apply attempt** | `linkedin.py:239-273` | Any failure in resume selection, phone fill, or Continue-click is indistinguishable from "form is unusual". Both branches log and move on. |
| C4 | **No duplicate suppression across runs** | `linkedin.py:157-196` | Already-applied detection is a per-page `contains(text(),'Applied')` check that only sees the current 25 cards. Restart → re-browse → re-apply. |
| C5 | **No CAPTCHA / challenge / MFA handling** | absent | Any such page is treated as "no Easy Apply button" → "Already applied!" → silently skipped. Or, if it appears mid-form, swallowed by C3. |
| C6 | **Credentials silently absent** | pre-checkpoint `config.py:7-8` | Placeholders looked like real values; the bot typed them and failed. Now fixed with `validateConfig()` + `sys.exit(1)`. |

### 12.2 High

| # | Issue | Location |
|---|---|---|
| H1 | `loadCookies()` has no error handling — a corrupt pickle kills startup | `linkedin.py:74` |
| H2 | `cookies/` is not in `.gitignore` | `.gitignore` |
| H3 | 16 `except` blocks, 6 bare `pass` | `linkedin.py` (measured) |
| H4 | 18 `time.sleep()`, 0 `WebDriverWait` | `linkedin.py` (measured) |
| H5 | Login detection depends on `//*[@id="ember14"]` | `linkedin.py:102` |
| H6 | 30 s fixed sleep after login click, then proceeds regardless | `linkedin.py:65` |
| H7 | Company blacklist matched against job title (fixed in checkpoint) | `linkedin.py:335` |
| H8 | `jobType` misspelled `Intership`; `Internship` silently dropped (fixed in checkpoint) | `utils.py:255,272` |
| H9 | Job count read from the first `//small` on the whole page, unscoped | `linkedin.py:139` |
| H10 | `pickle.load` on an untrusted file is a code-execution vector | `linkedin.py:76` |
| H11 | No test suite of any kind | absent |
| H12 | `requirements.yaml` omits `pyyaml` and duplicates `requirements.txt` | `requirements.yaml` |
| H13 | `python-dotenv` used but not declared | `requirements.txt` |

### 12.3 Medium / low

- `config.py` has no schema; a typo like `locaion = ["India"]` fails silently.
- `jobsToPages` caps at 40 pages with no logging when the cap is hit.
- `print(e)` raw traceback text leaks to console at `linkedin.py:351,361`.
- `donate()` and the `www.automated-bots.com` banner are hardcoded.
- `constants.testJobUrl` contains a stale hardcoded `geoId` and a real job ID.
- Docker path installs `google-chrome-stable`; unusable on the Windows host.
- `.kilo/worktrees/` contains a full duplicate of the repo inside the repo.
- `sys.stdout.reconfigure(encoding='utf-8')` at import time in two modules
  crashes on a non-UTF8 console.
- `Linkedin.remote()` does not prefix `&` on the first value
  (`"f_WT=1"` not `"&f_WT=1"`); it works only by accident of the preceding
  `jobType()` always appending `&`.

---

## 13. WHERE AI CANNOT CURRENTLY HELP

Because the job description is never extracted, no AI feature is possible
today without first building extraction. Specifically unavailable:

- requirement extraction, must-have vs nice-to-have split
- semantic job↔resume matching
- ATS keyword analysis
- cover-letter generation
- evidence-grounded question answering
- resume tailoring
- job quality / spam detection
- seniority inference
- contradiction detection between resume and profile

Available today with no JD text: deterministic title/company/location
blacklisting only.

## 14. WHERE A HUMAN MUST INTERVENE

The code has **no** human-in-the-loop mechanism. A human is required today by
accident, when:

- a CAPTCHA or `/checkpoint/challenge/` appears (bot silently skips or hangs)
- 2FA or email verification is triggered at login
- the resume list is empty or the positional index is wrong
- a multi-step form asks a question the bot cannot answer
- `chooseResume()` silently no-ops and the wrong resume is submitted
- the user wants to know *why* a job was skipped

The only user-facing affordances are the fixed text log and, if
`displayWarnings` is on, yellow warning lines.

---

## 15. MEASURED BASELINE (target machine)

| Check | Result |
|---|---|
| Python | 3.11.8, venv active at `venv\Scripts\python.exe` |
| `import config, constants, utils, linkedin` | clean |
| `utils.validateConfig()` | 1 finding (credentials empty) — **expected and correct** |
| YAML parse | OK — 165 inputField / 48 radio / 51 dropdown |
| Chrome binary | **NOT INSTALLED** on this machine |
| Edge binary | `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, 154.0.4258.37 |
| chromedriver | webdriver-manager resolves 154.0.8037.92, file present |
| `webdriver.Chrome()` | **FAILS** — `SessionNotCreatedException: cannot find Chrome binary` |
| `utils.createDriver()` | **PASS** — falls back to Edge, loads LinkedIn, clean quit |
| URL generation | 10 URLs, all filters present, `urlToKeywords` round-trips |
| Job cards logged out | `//li[@data-occludable-job-id]` → **0 matches** (expected; needs login) |
| `writeResults` + summary | **PASS** after checkpoint fix |

---

## 16. AUDIT FINDINGS THAT NEED A HUMAN DECISION

These are not bugs to fix silently. Each changes behaviour or policy.

### 16.1 Anti-detection code
`--disable-blink-features=AutomationControlled`, `excludeSwitches`,
`useAutomationExtension=False`, and `selenium_stealth` exist upstream. Target
design §27 prohibits evasion techniques. **Decision needed:** keep as-is
(user's own account, upstream behaviour, removing it may break the login
flow), or strip. Recommend: keep, document, do not extend.

### 16.2 Docker path
The Dockerfile is Linux-only and the user is on Windows with Edge.
**Decision needed:** maintain Docker as a secondary path, or retire it.
Recommend: retire from the critical path, keep the file, document Windows-first.

### 16.3 `additionalQuestions.yaml`
263 of 264 entries are another person's data and are dead in the free version.
Deleting them is a large diff on a tracked file with no functional benefit;
keeping them is a privacy/hygiene smell and a hallucination risk if a future
question engine starts reading them.
**Decision needed:** recommend quarantining the file into
`data/profile/answers.json` (new format, user-owned, git-ignored) and
deprecating the YAML.

### 16.4 Anti-bot / ToS posture
The upstream README states the risk of bans is "very low". This is not a
guarantee. The target design's stance (no evasion, pause on challenge, human
confirmation before submit) is strictly safer and is what §29 requires.
**Decision needed:** none — the target design already decides this. Flagging
that it is a behavioural reduction in volume by design.

### 16.5 Real submission policy
`config.dryRun` is currently `True` and `maxApplicationsPerRun` is `5`. These
were set during the previous task and must stay `True` until the user
explicitly changes them. Target design adds `SAFE_MODE` + `SubmitGuard` +
human confirmation **on top**, never instead.

---

## 17. WHAT THE CHECKPOINT COMMIT (`4717b55`) ALREADY CHANGED

Recorded for traceability. This predates the upgrade and is **not** part of it.

- Credentials moved from hardcoded `config.py` to `.env` via `python-dotenv`
- `cookies_path`, GlobalLogic Pro PII placeholders, and `AngelCo*` globals
  removed/emptied
- `browser` switched to `["Edge"]`; `utils.createDriver()` added with binary
  detection and Chrome↔Edge fallback
- `utils.validateConfig()` and `utils.printRunBanner()` added; `main()` now
  fails fast on missing credentials and quits the driver on exit
- `submitApplication()` introduced as the single submit site, refusing to click
  while `dryRun` is `True`
- Dry-run candidates now count toward `maxApplicationsPerRun` (previously the
  cap could never fire in dry-run, so a dry run would browse unbounded)
- `writeResults()` rewritten as append-only (was erasing the session summary)
- `jobType` accepts correct `Internship` spelling
- Search keywords URL-encoded; `urlToKeywords` decodes them
- Company blacklist now matches the company string, not the job title
- `KeyboardInterrupt` handled

---

## 18. AUDIT CONCLUSION

The project is a **working but fragile single-file scraper**. Its value is
that it already solves the hardest external problem: reliably driving
LinkedIn's Easy Apply DOM in a logged-in session. Its weakness is that it
treats every step as infallible, keeps no memory, reads no job description,
and records success without verification.

The upgrade is therefore **additive, not a rewrite**: the Selenium layer stays
and becomes provider #1; everything upstream of it (collection → matching →
generation → review) and everything downstream of it (verification → tracker)
is new.

**Highest-risk areas for the upgrade, in order:**

1. The submit path (`linkedin.py:315`, `applyProcess`) — must become guarded
   and verified without regressing the working dry-run behaviour
2. Step-count inference (`math.floor(100/percentage) - 2`) — must be replaced
   with DOM-derived state
3. Login/session — must gain challenge detection and resumable cookies
4. Selector fragility — must be centralized with fallbacks and explicit waits
5. The 263 dead YAML answers — must never become a live answer source

**Not a single line of the existing automation needs to be deleted.** It needs
to be wrapped, guarded, and made observable.
