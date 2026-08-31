from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd
import requests


ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv("CAREER_TRACKER_DB", ROOT / "career_tracker.db"))

COUNTRIES = {
    "Japan": "jp", "Singapore": "sg", "China": "cn",
    "United States": "us", "United Kingdom": "gb",
}
SOURCES = ("Arbeitnow", "Remotive", "Adzuna", "Greenhouse", "Lever", "USAJOBS")
JOB_COLUMNS = ["id", "title", "company", "location", "country", "job_type",
               "workplace_type", "degree_level", "remote", "posted_at", "opens_at",
               "deadline", "source", "url", "description"]


FIELDS = {
    "Technology": ["Software engineering", "Data science", "Cybersecurity", "Cloud & DevOps", "Product management"],
    "Business": ["Strategy", "Operations", "Business analysis", "Entrepreneurship", "Consulting"],
    "Finance": ["Investment banking", "Asset management", "Accounting", "Risk", "Fintech"],
    "Healthcare": ["Clinical care", "Public health", "Health informatics", "Pharmacy", "Biotechnology"],
    "Engineering": ["Mechanical", "Electrical", "Civil", "Chemical", "Industrial"],
    "Science": ["Biology", "Chemistry", "Physics", "Earth science", "Research"],
    "Education": ["Teaching", "Curriculum", "Education technology", "Student services", "Research"],
    "Law & policy": ["Legal", "Compliance", "Public policy", "Government", "International affairs"],
    "Design": ["UX/UI", "Graphic design", "Product design", "Architecture", "Industrial design"],
    "Media & communications": ["Journalism", "Public relations", "Content", "Publishing", "Broadcasting"],
    "Marketing": ["Digital marketing", "Brand", "Growth", "Market research", "Advertising"],
    "Sales & customer success": ["B2B sales", "Retail", "Account management", "Customer success", "Sales operations"],
    "Arts & culture": ["Performing arts", "Museums", "Film", "Music", "Arts administration"],
    "Environment & sustainability": ["Climate", "Renewable energy", "Conservation", "ESG", "Environmental engineering"],
    "Manufacturing & supply chain": ["Manufacturing", "Logistics", "Procurement", "Quality", "Supply chain analytics"],
    "Hospitality & tourism": ["Hotels", "Travel", "Events", "Food service", "Tourism management"],
    "Human resources": ["Recruiting", "People operations", "Learning & development", "Compensation", "HR analytics"],
    "Nonprofit & social impact": ["Programs", "Fundraising", "Community outreach", "Social services", "Impact measurement"],
}

SKILLS = {
    "software": ["Python or JavaScript", "Git", "data structures", "testing", "system design"],
    "data": ["SQL", "Python or R", "statistics", "data visualization", "experimentation"],
    "design": ["user research", "prototyping", "Figma", "accessibility", "portfolio storytelling"],
    "marketing": ["analytics", "copywriting", "campaign strategy", "SEO/SEM", "experimentation"],
    "finance": ["financial modeling", "Excel", "accounting", "valuation", "presentation"],
    "default": ["communication", "research", "problem solving", "project management", "domain knowledge"],
}


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    with connection() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS profiles (
          username TEXT PRIMARY KEY, degree TEXT, field TEXT, subfield TEXT,
          keywords TEXT, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
          username TEXT PRIMARY KEY, phone TEXT NOT NULL, query TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
          consented_at TEXT
        );
        CREATE TABLE IF NOT EXISTS snapshots (
          captured_on TEXT NOT NULL, job_id TEXT NOT NULL, title TEXT NOT NULL,
          company TEXT, location TEXT, source TEXT, url TEXT, posted_at TEXT,
          username TEXT NOT NULL DEFAULT '', query TEXT NOT NULL DEFAULT '',
          PRIMARY KEY (captured_on, username, query, job_id)
        );
        CREATE TABLE IF NOT EXISTS delivered_jobs (
          username TEXT NOT NULL, job_id TEXT NOT NULL, delivered_at TEXT NOT NULL,
          PRIMARY KEY (username, job_id)
        );
        """)
        existing = {row[1] for row in con.execute("PRAGMA table_info(snapshots)")}
        for column in ("country", "job_type", "workplace_type"):
            if column not in existing:
                con.execute(f"ALTER TABLE snapshots ADD COLUMN {column} TEXT")
        profile_columns = {row[1] for row in con.execute("PRAGMA table_info(profiles)")}
        if "gender" not in profile_columns:
            con.execute("ALTER TABLE profiles ADD COLUMN gender TEXT")
        subscription_columns = {row[1] for row in con.execute("PRAGMA table_info(subscriptions)")}
        if "consented_at" not in subscription_columns:
            con.execute("ALTER TABLE subscriptions ADD COLUMN consented_at TEXT")

        # Older databases keyed snapshots only by date and job. Rebuild the table
        # so different users and queries cannot overwrite or merge one another.
        snapshot_info = list(con.execute("PRAGMA table_info(snapshots)"))
        snapshot_columns = {row[1] for row in snapshot_info}
        pk_columns = [row[1] for row in sorted(snapshot_info, key=lambda row: row[5]) if row[5]]
        if "username" not in snapshot_columns or "query" not in snapshot_columns or pk_columns != ["captured_on", "username", "query", "job_id"]:
            con.executescript("""
            CREATE TABLE snapshots_v2 (
              captured_on TEXT NOT NULL, job_id TEXT NOT NULL, title TEXT NOT NULL,
              company TEXT, location TEXT, source TEXT, url TEXT, posted_at TEXT,
              country TEXT, job_type TEXT, workplace_type TEXT,
              username TEXT NOT NULL DEFAULT '', query TEXT NOT NULL DEFAULT '',
              PRIMARY KEY (captured_on, username, query, job_id)
            );
            INSERT OR IGNORE INTO snapshots_v2
              (captured_on, job_id, title, company, location, source, url, posted_at,
               country, job_type, workplace_type)
            SELECT captured_on, job_id, title, company, location, source, url, posted_at,
                   country, job_type, workplace_type FROM snapshots;
            DROP TABLE snapshots;
            ALTER TABLE snapshots_v2 RENAME TO snapshots;
            """)


def profile(username: str) -> dict | None:
    with connection() as con:
        row = con.execute("SELECT * FROM profiles WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def save_profile(username: str, degree: str, field: str, subfield: str, keywords: str,
                 gender: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.execute("""INSERT INTO profiles (username, degree, field, subfield, keywords, updated_at, gender)
          VALUES (?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(username) DO UPDATE SET degree=excluded.degree, field=excluded.field,
          subfield=excluded.subfield, keywords=excluded.keywords, updated_at=excluded.updated_at,
          gender=excluded.gender""",
          (username, degree, field, subfield, keywords, now, gender or None))


def save_subscription(username: str, phone: str, query: str, enabled: bool = True) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.execute("""INSERT INTO subscriptions
          (username, phone, query, enabled, updated_at, consented_at) VALUES (?, ?, ?, ?, ?, ?)
          ON CONFLICT(username) DO UPDATE SET phone=excluded.phone, query=excluded.query,
          enabled=excluded.enabled, updated_at=excluded.updated_at,
          consented_at=CASE WHEN excluded.enabled=1 THEN excluded.consented_at ELSE subscriptions.consented_at END""",
          (username, phone, query, int(enabled), now, now if enabled else None))


def subscription(username: str) -> dict | None:
    with connection() as con:
        row = con.execute("SELECT * FROM subscriptions WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def disable_subscription(username: str) -> None:
    with connection() as con:
        con.execute("UPDATE subscriptions SET enabled=0, updated_at=? WHERE username=?",
                    (datetime.now(timezone.utc).isoformat(), username))


def subscriptions() -> list[dict]:
    with connection() as con:
        return [dict(r) for r in con.execute("SELECT * FROM subscriptions WHERE enabled=1")]


def _clean_html(value: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def _job_id(source: str, url: str, title: str, company: str) -> str:
    return hashlib.sha256(f"{source}|{url}|{title}|{company}".encode()).hexdigest()[:24]


def _parse_date(value: str | None) -> pd.Timestamp:
    if isinstance(value, (int, float)):
        parsed = pd.to_datetime(value, unit="s", utc=True, errors="coerce")
    else:
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return parsed


def _csv_env(name: str) -> list[str]:
    return [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]


def _country(location: str) -> str:
    """Normalize common country names/codes found in provider location strings."""
    text = f" {location.lower()} "
    aliases = {
        "Japan": (" japan ", " tokyo", " osaka", " jp "),
        "Singapore": (" singapore", " sg "),
        "China": (" china", " beijing", " shanghai", " shenzhen", " cn "),
        "United States": (" united states", " usa", " u.s.", " us ", "new york", "california"),
        "United Kingdom": (" united kingdom", " uk ", "england", "london", "scotland", "wales"),
    }
    for country, needles in aliases.items():
        if any(needle in text for needle in needles):
            return country
    return "Other / unspecified"


def _job_type(value: str) -> str:
    text = (value or "").lower()
    if re.search(r"\bintern(?:ship)?\b", text):
        return "Internship"
    if re.search(r"\bpart[- ]?time\b", text):
        return "Part-time"
    if re.search(r"\b(contract|temporary|freelance)\b", text):
        return "Contract / temporary"
    if re.search(r"\bfull[- ]?time\b|\bpermanent\b", text):
        return "Full-time"
    return "Not specified"


def _degree_level(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if re.search(r"\b(ph\.?d|doctorate|doctoral)\b", text):
        return "PhD / doctorate"
    if re.search(r"\b(master(?:'?s)?|msc|mba|graduate degree)\b", text):
        return "Graduate / master's"
    if re.search(r"\b(bachelor(?:'?s)?|undergraduate|bsc|entry[- ]level|new grad)\b", text):
        return "Undergraduate / entry level"
    if re.search(r"\b(associate degree|diploma|certificate)\b", text):
        return "Associate / certificate"
    return "Any / not specified"


def degree_matches(profile_degree: str, job_degree: str) -> bool:
    """Keep unspecified roles and roles compatible with the user's current degree."""
    if job_degree == "Any / not specified" or profile_degree in {"Other", "Not currently studying", ""}:
        return True
    allowed = {
        "Undergraduate": {"Undergraduate / entry level", "Associate / certificate"},
        "Graduate / master's": {"Graduate / master's", "Undergraduate / entry level", "Associate / certificate"},
        "PhD / doctorate": {"PhD / doctorate", "Graduate / master's", "Undergraduate / entry level", "Associate / certificate"},
        "Associate": {"Associate / certificate"},
        "Certificate / bootcamp": {"Associate / certificate", "Undergraduate / entry level"},
    }
    return job_degree in allowed.get(profile_degree, set())


def _matches(query: str, *values: object) -> bool:
    terms = [term for term in re.split(r"\s+", query.lower().strip()) if term]
    haystack = " ".join(str(value or "") for value in values).lower()
    return not terms or all(term in haystack for term in terms)


def _append(jobs: list[dict], *, source: str, title: str, company: str, location: str,
            url: str, description: str = "", posted_at: object = None, deadline: object = None,
            opens_at: object = None,
            job_type: str = "", workplace_type: str = "", remote: bool = False,
            country: str = "") -> None:
    location = location or "Not specified"
    workplace = workplace_type.title() if workplace_type else ("Remote" if remote else "Not specified")
    jobs.append({"id": _job_id(source, url, title, company), "title": title or "Untitled role",
        "company": company or "Unknown", "location": location, "country": country or _country(location),
        "job_type": _job_type(job_type or title), "workplace_type": workplace,
        "degree_level": _degree_level(title, description), "remote": remote or workplace.lower() == "remote",
        "posted_at": _parse_date(posted_at), "opens_at": pd.to_datetime(opens_at, utc=True, errors="coerce"),
        "deadline": pd.to_datetime(deadline, utc=True, errors="coerce"),
        "source": source, "url": url, "description": _clean_html(description)[:500]})


def fetch_jobs(query: str, limit: int = 3_000, countries: Iterable[str] | None = None,
               sources: Iterable[str] | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Fetch and normalize current roles. Optional providers activate through environment variables."""
    jobs: list[dict] = []
    errors: list[str] = []
    headers = {"User-Agent": "CareerCompass/1.0 (educational job tracker)"}
    wanted_sources = set(sources or SOURCES)
    wanted_countries = set(countries or COUNTRIES)

    try:
        if "Arbeitnow" not in wanted_sources:
            raise StopIteration
        next_url = "https://www.arbeitnow.com/api/job-board-api"
        # Read a few pages so one Europe-heavy first page does not crowd out other locations.
        for _ in range(3):
            response = requests.get(next_url, timeout=12, headers=headers)
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("data", []):
                if not _matches(query, item.get("title"), item.get("description"), item.get("tags")):
                    continue
                posted = _parse_date(item.get("created_at"))
                url = item.get("url", "")
                title, company = item.get("title", "Untitled role"), item.get("company_name", "Unknown")
                _append(jobs, source="Arbeitnow", url=url, title=title, company=company,
                        location=item.get("location") or "Not specified", remote=bool(item.get("remote")),
                        posted_at=posted, description=item.get("description", ""), job_type=" ".join(item.get("job_types", [])))
            next_url = (payload.get("links") or {}).get("next") or payload.get("next_page_url")
            if not next_url:
                break
    except StopIteration:
        pass
    except (requests.RequestException, ValueError) as exc:
        errors.append(f"Arbeitnow: {exc}")

    try:
        if "Remotive" not in wanted_sources:
            raise StopIteration
        response = requests.get("https://remotive.com/api/remote-jobs", params={"search": query, "limit": limit}, timeout=12, headers=headers)
        response.raise_for_status()
        for item in response.json().get("jobs", []):
            posted = _parse_date(item.get("publication_date"))
            url = item.get("url", "")
            title, company = item.get("title", "Untitled role"), item.get("company_name", "Unknown")
            _append(jobs, source="Remotive", url=url, title=title, company=company,
                    location=item.get("candidate_required_location") or "Remote", remote=True, posted_at=posted,
                    description=item.get("description", ""), job_type=item.get("job_type", ""), workplace_type="Remote")
    except StopIteration:
        pass
    except (requests.RequestException, ValueError) as exc:
        errors.append(f"Remotive: {exc}")

    adzuna_id, adzuna_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    # Adzuna currently exposes Singapore, US, and UK endpoints among the target markets.
    if "Adzuna" in wanted_sources and adzuna_id and adzuna_key:
        for country in wanted_countries & {"Singapore", "United States", "United Kingdom"}:
            try:
                code = COUNTRIES[country]
                response = requests.get(f"https://api.adzuna.com/v1/api/jobs/{code}/search/1",
                    params={"app_id": adzuna_id, "app_key": adzuna_key, "what": query,
                            "results_per_page": min(limit, 50), "content-type": "application/json"}, timeout=12, headers=headers)
                response.raise_for_status()
                for item in response.json().get("results", []):
                    _append(jobs, source="Adzuna", title=item.get("title", ""),
                        company=(item.get("company") or {}).get("display_name", "Unknown"),
                        location=(item.get("location") or {}).get("display_name", country), country=country,
                        url=item.get("redirect_url", ""), description=item.get("description", ""),
                        posted_at=item.get("created"), job_type=item.get("contract_time") or item.get("contract_type", ""))
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"Adzuna ({country}): {exc}")

    if "Greenhouse" in wanted_sources:
        for board in _csv_env("GREENHOUSE_BOARDS"):
            try:
                response = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                                        params={"content": "true"}, timeout=12, headers=headers)
                response.raise_for_status()
                for item in response.json().get("jobs", []):
                    location = (item.get("location") or {}).get("name", "Not specified")
                    if _matches(query, item.get("title"), item.get("content")):
                        _append(jobs, source="Greenhouse", title=item.get("title", ""), company=board,
                            location=location, url=item.get("absolute_url", ""), description=item.get("content", ""),
                            posted_at=item.get("first_published") or item.get("updated_at"),
                            opens_at=item.get("first_published"), deadline=item.get("application_deadline"),
                            job_type=item.get("title", ""))
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"Greenhouse ({board}): {exc}")

    if "Lever" in wanted_sources:
        for site in _csv_env("LEVER_SITES"):
            try:
                response = requests.get(f"https://api.lever.co/v0/postings/{site}",
                                        params={"mode": "json"}, timeout=12, headers=headers)
                response.raise_for_status()
                for item in response.json():
                    categories = item.get("categories") or {}
                    if _matches(query, item.get("text"), item.get("descriptionPlain"), categories):
                        _append(jobs, source="Lever", title=item.get("text", ""), company=site,
                            location=categories.get("location", "Not specified"), url=item.get("hostedUrl") or item.get("applyUrl", ""),
                            description=item.get("descriptionPlain", ""), posted_at=item.get("created", 0) / 1000,
                            job_type=categories.get("commitment", ""), workplace_type=item.get("workplaceType", ""))
            except (requests.RequestException, ValueError, TypeError) as exc:
                errors.append(f"Lever ({site}): {exc}")

    usajobs_key, usajobs_email = os.getenv("USAJOBS_API_KEY"), os.getenv("USAJOBS_EMAIL")
    if "USAJOBS" in wanted_sources and usajobs_key and usajobs_email:
        try:
            response = requests.get("https://data.usajobs.gov/api/search",
                params={"Keyword": query, "ResultsPerPage": min(limit, 500)}, timeout=12,
                headers={"Authorization-Key": usajobs_key, "User-Agent": usajobs_email})
            response.raise_for_status()
            for result in (response.json().get("SearchResult") or {}).get("SearchResultItems", []):
                item = result.get("MatchedObjectDescriptor") or {}
                locations = item.get("PositionLocation") or []
                location = "; ".join(value.get("LocationName", "") for value in locations if value.get("LocationName"))
                details = (item.get("UserArea") or {}).get("Details") or {}
                schedules = item.get("PositionSchedule") or []
                _append(jobs, source="USAJOBS", title=item.get("PositionTitle", ""),
                    company=item.get("OrganizationName", "U.S. Federal Government"),
                    location=location or "United States", country="United States",
                    url=item.get("PositionURI", ""),
                    description=" ".join(str(details.get(key, "")) for key in ("MajorDuties", "Requirements", "Education")),
                    posted_at=item.get("PublicationStartDate") or item.get("PositionStartDate"),
                    opens_at=item.get("PositionStartDate"),
                    deadline=item.get("ApplicationCloseDate") or item.get("PositionEndDate"),
                    job_type=" ".join(value.get("Name", "") for value in schedules))
        except (requests.RequestException, ValueError, TypeError) as exc:
            errors.append(f"USAJOBS: {exc}")

    if not jobs:
        return pd.DataFrame(columns=JOB_COLUMNS), errors
    frame = pd.DataFrame(jobs).drop_duplicates("id").sort_values("posted_at", ascending=False)
    frame = frame[frame.country.isin(wanted_countries) | frame.country.eq("Other / unspecified")].head(limit)
    return frame, errors


def classify_jobs(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "opens_at" not in result:
        result["opens_at"] = pd.NaT
    if "degree_level" not in result:
        result["degree_level"] = result.apply(
            lambda row: _degree_level(str(row.get("title", "")), str(row.get("description", ""))), axis=1)
    now = pd.Timestamp.now(tz="UTC")
    result["status"] = "Recruiting now"
    deadline = pd.to_datetime(result["deadline"], utc=True, errors="coerce")
    result.loc[deadline.notna() & (deadline < now), "status"] = "Past known deadline"
    opens_at = pd.to_datetime(result["opens_at"], utc=True, errors="coerce")
    result.loc[opens_at.notna() & (opens_at > now), "status"] = "Applications open soon"
    result["new_this_week"] = pd.to_datetime(result["posted_at"], utc=True) >= now - pd.Timedelta(days=7)
    return result


def fetch_usajobs_history(query: str, start: str, end: str, limit: int = 500,
                          scan_limit: int = 5_000) -> tuple[pd.DataFrame, str | None]:
    """Search the public U.S. federal announcement archive by date, then title locally."""
    jobs: list[dict] = []
    scanned = 0
    url = "https://data.usajobs.gov/api/historicjoa"
    params: dict | None = {"StartPositionOpenDate": pd.Timestamp(start).strftime("%m-%d-%Y"),
                           "EndPositionOpenDate": pd.Timestamp(end).strftime("%m-%d-%Y")}
    headers = {"User-Agent": "CareerCompass/1.0 (educational job tracker)"}
    try:
        while url and scanned < scan_limit and len(jobs) < limit:
            response = requests.get(url, params=params, timeout=20, headers=headers)
            response.raise_for_status()
            payload = response.json()
            page = payload.get("data", [])
            scanned += len(page)
            for item in page:
                title = item.get("positionTitle", "")
                agency = item.get("hiringAgencyName", "")
                if not _matches(query, title, agency):
                    continue
                locations = item.get("positionLocations") or []
                location = "; ".join(", ".join(filter(None, [value.get("positionLocationCity"),
                    value.get("positionLocationState"), value.get("positionLocationCountry")])) for value in locations)
                control = str(item.get("usajobsControlNumber", ""))
                opened = pd.to_datetime(item.get("positionOpenDate"), utc=True, errors="coerce")
                closed = pd.to_datetime(item.get("positionCloseDate"), utc=True, errors="coerce")
                expired = pd.to_datetime(item.get("positionExpireDate"), utc=True, errors="coerce")
                actual_close = expired if not pd.isna(expired) and (pd.isna(opened) or expired >= opened) else closed
                _append(jobs, source="USAJOBS Historic", title=title, company=agency,
                    location=location or "United States", country="United States",
                    url=f"https://www.usajobs.gov/GetJob/ViewDetails/{control}",
                    posted_at=opened, opens_at=opened, deadline=actual_close,
                    job_type=item.get("workSchedule", ""),
                    description=item.get("positionOpeningStatus", ""))
                if len(jobs) >= limit:
                    break
            next_path = (payload.get("paging") or {}).get("next")
            url = f"https://data.usajobs.gov{next_path}" if next_path and next_path.startswith("/") else next_path
            params = None
    except (requests.RequestException, ValueError, TypeError) as exc:
        return pd.DataFrame(columns=JOB_COLUMNS), str(exc)
    frame = pd.DataFrame(jobs, columns=JOB_COLUMNS)
    note = f"Scanned {scanned:,} federal announcements; results are capped at {limit:,}."
    return frame, note


def record_snapshot(frame: pd.DataFrame, captured_on: str | None = None,
                    username: str = "", query: str = "") -> None:
    day = captured_on or datetime.now(timezone.utc).date().isoformat()
    rows = [(day, r.id, r.title, r.company, r.location, r.source, r.url,
             None if pd.isna(r.posted_at) else r.posted_at.isoformat(), r.country,
             r.job_type, r.workplace_type, username, query) for r in frame.itertuples()]
    with connection() as con:
        con.executemany("""INSERT OR IGNORE INTO snapshots
            (captured_on, job_id, title, company, location, source, url, posted_at,
             country, job_type, workplace_type, username, query)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)


def tracker_breakdown(days: int = 31, username: str = "", query: str = "") -> pd.DataFrame:
    """Latest observed counts grouped for the Insights source/country tracker."""
    with connection() as con:
        return pd.read_sql_query("""SELECT captured_on AS date, source, COALESCE(country, 'Other / unspecified') AS country,
            COUNT(*) AS jobs FROM snapshots WHERE captured_on >= date('now', ?)
            AND username=? AND query=?
            GROUP BY captured_on, source, country ORDER BY captured_on""", con,
            params=(f"-{days} days", username, query))


def tracker_breakdown_between(start: str, end: str, username: str = "",
                              query: str | None = "") -> pd.DataFrame:
    """Observed source/country counts inside an inclusive calendar range."""
    with connection() as con:
        query_filter = " AND query=?" if query is not None else ""
        params = (start, end, username, query) if query is not None else (start, end, username)
        return pd.read_sql_query(f"""SELECT captured_on AS date, source,
            COALESCE(country, 'Other / unspecified') AS country, COUNT(*) AS jobs
            FROM (SELECT DISTINCT captured_on, job_id, source, country FROM snapshots
                  WHERE captured_on BETWEEN ? AND ? AND username=?{query_filter})
            GROUP BY captured_on, source, country ORDER BY captured_on""", con, params=params)


def trend(days: int, username: str = "", query: str = "") -> pd.DataFrame:
    with connection() as con:
        df = pd.read_sql_query("""SELECT captured_on, job_id FROM snapshots
            WHERE captured_on >= date('now', ?) AND username=? AND query=?""", con,
            params=(f"-{days} days", username, query))
    if df.empty:
        return pd.DataFrame(columns=["date", "new jobs", "disappeared jobs", "market jobs"])
    by_day = {day: set(group.job_id) for day, group in df.groupby("captured_on")}
    output, prior = [], set()
    for day in sorted(by_day):
        current = by_day[day]
        output.append({"date": pd.to_datetime(day), "new jobs": len(current - prior),
                       "disappeared jobs": len(prior - current), "market jobs": len(current)})
        prior = current
    return pd.DataFrame(output)


def trend_between(start: str, end: str, username: str = "",
                  query: str | None = "") -> pd.DataFrame:
    """Movement in an inclusive range, using the preceding snapshot as baseline."""
    with connection() as con:
        query_filter = " AND query=?" if query is not None else ""
        outer_params = (username, query, end, start) if query is not None else (username, end, start)
        prior_params = (username, query, start) if query is not None else (username, start)
        df = pd.read_sql_query(f"""SELECT DISTINCT captured_on, job_id FROM snapshots
            WHERE username=?{query_filter} AND captured_on <= ? AND
              (captured_on >= ? OR captured_on = (
                SELECT MAX(captured_on) FROM snapshots
                WHERE username=?{query_filter} AND captured_on < ?))
            ORDER BY captured_on""", con,
            params=(*outer_params, *prior_params))
    if df.empty:
        return pd.DataFrame(columns=["date", "new jobs", "disappeared jobs", "market jobs"])
    by_day = {day: set(group.job_id) for day, group in df.groupby("captured_on")}
    output, prior = [], set()
    for day in sorted(by_day):
        current = by_day[day]
        if day >= start:
            output.append({"date": pd.to_datetime(day), "new jobs": len(current - prior),
                           "disappeared jobs": len(prior - current), "market jobs": len(current)})
        prior = current
    return pd.DataFrame(output, columns=["date", "new jobs", "disappeared jobs", "market jobs"])


def snapshot_bounds(username: str = "", query: str | None = "") -> tuple[str | None, str | None]:
    with connection() as con:
        if query is None:
            row = con.execute("""SELECT MIN(captured_on), MAX(captured_on) FROM snapshots
                               WHERE username=?""", (username,)).fetchone()
        else:
            row = con.execute("""SELECT MIN(captured_on), MAX(captured_on) FROM snapshots
                               WHERE username=? AND query=?""", (username, query)).fetchone()
    return row[0], row[1]


def snapshot_rows_between(start: str, end: str, username: str = "",
                          query: str | None = "") -> pd.DataFrame:
    """Raw user-owned observations for inspection or export."""
    with connection() as con:
        query_filter = " AND query=?" if query is not None else ""
        params = (start, end, username, query) if query is not None else (start, end, username)
        return pd.read_sql_query(f"""SELECT captured_on AS date, query, title, company,
            country, location, job_type, workplace_type, source, posted_at, url
            FROM snapshots WHERE captured_on BETWEEN ? AND ? AND username=?{query_filter}
            ORDER BY captured_on, title, company""", con, params=params)


def suggested_skills(text: str) -> list[str]:
    lower = text.lower()
    for key, values in SKILLS.items():
        if key != "default" and key in lower:
            return values
    return SKILLS["default"]


def undelivered_jobs(username: str, frame: pd.DataFrame) -> pd.DataFrame:
    """Return listings that have never been successfully sent to this user."""
    if frame.empty:
        return frame
    with connection() as con:
        delivered = {row[0] for row in con.execute(
            "SELECT job_id FROM delivered_jobs WHERE username=?", (username,))}
    return frame[~frame.id.isin(delivered)]


def mark_jobs_delivered(username: str, job_ids: Iterable[str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.executemany("INSERT OR IGNORE INTO delivered_jobs VALUES (?, ?, ?)",
                        [(username, job_id, now) for job_id in job_ids])


init_db()
