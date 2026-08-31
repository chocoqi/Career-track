from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from urllib.parse import quote_plus

import altair as alt
import pandas as pd
import streamlit as st

from auth import (account_exists, account_name, create_account, create_session, delete_account, end_session, link_accounts,
                  linked_accounts, reset_password, session_username, verify_password,
                  verify_recovery_code)
from career_data import (COUNTRIES, FIELDS, SOURCES, classify_jobs, degree_matches, disable_subscription,
                         fetch_jobs, fetch_usajobs_history, profile, record_snapshot, save_profile, save_subscription, subscription, suggested_skills,
                         snapshot_bounds, snapshot_rows_between, tracker_breakdown, tracker_breakdown_between,
                         trend, trend_between)


st.set_page_config(page_title="Career compass", page_icon=":material/explore:", layout="wide")

browser_session = st.components.v2.component(
    "browser_session",
    js="""
    export default function(component) {
        const {data, setStateValue} = component;
        const storageKey = "career_compass_session_token";

        if (data.action === "save") {
            localStorage.setItem(storageKey, data.token);
        } else if (data.action === "clear") {
            localStorage.removeItem(storageKey);
        }

        setStateValue("token", localStorage.getItem(storageKey));
        setStateValue("ready", true);
    }
    """,
)

for key, value in {"username": "", "login_username": "", "logged_in": False,
                   "jobs": None, "messages": [], "editing_profile": False, "browser_session_action": "load",
                   "browser_session_checked": False, "session_token": "", "welcome_back": False,
                   "active_page": "Jobs", "auth_mode": "Sign in", "recovery_username": "",
                   "new_recovery_code": "", "account_view": None, "recovery_reason": "account",
                   "added_recovery_code": "", "added_account_name": "",
                   "historic_jobs": None, "historic_jobs_note": ""}.items():
    st.session_state.setdefault(key, value)

saved_session = browser_session(
    data={"action": st.session_state.browser_session_action, "token": st.session_state.session_token},
    key="browser_session_storage",
    on_ready_change=lambda: None,
    on_token_change=lambda: None,
)

if st.session_state.browser_session_action == "load" and not st.session_state.browser_session_checked:
    if not saved_session.ready:
        st.spinner("Restoring your session...")
        st.stop()
    st.session_state.browser_session_checked = True
    restored_username = session_username(saved_session.token)
    if restored_username:
        st.session_state.session_token = saved_session.token
        st.session_state.username = restored_username
        st.session_state.logged_in = True
        st.session_state.welcome_back = True


@st.cache_data(ttl="30m", max_entries=40, show_spinner=False)
def cached_jobs(query: str) -> tuple[pd.DataFrame, list[str]]:
    return fetch_jobs(query)


@st.cache_data(ttl="6h", max_entries=20, show_spinner=False)
def cached_historic_jobs(query: str, start: str, end: str) -> tuple[pd.DataFrame, str | None]:
    return fetch_usajobs_history(query, start, end)


def _password_error(password: str, confirmation: str) -> str | None:
    if len(password) < 10:
        return "Use at least 10 characters for the password."
    if len(password) > 1024:
        return "The password is too long."
    if password != confirmation:
        return "The passwords do not match."
    return None


def _start_login(username: str) -> None:
    st.session_state.username = username
    st.session_state.session_token = create_session(username)
    st.session_state.logged_in = True
    st.session_state.browser_session_action = "save"
    st.session_state.welcome_back = True


def _show_sign_in() -> None:
    st.session_state.auth_mode = "Sign in"
    st.session_state.recovery_username = ""
    st.session_state.new_recovery_code = ""


def login() -> None:
    with st.container(horizontal_alignment="center"):
        with st.container(width=520):
            _login_panel()


def _login_panel() -> None:
    st.title("See where the opportunities are moving")
    st.write("Track live roles, understand market movement, and turn your studies into a career plan.")

    if st.session_state.new_recovery_code:
        action = "Password reset" if st.session_state.recovery_reason == "reset" else "Account created"
        st.success(f"{action}. Save this recovery code now; it will not be shown again.")
        st.code(st.session_state.new_recovery_code, language=None)
        st.warning("If both your password and recovery code are lost, the account cannot be recovered.")
        st.button("I saved it - go to sign in", type="primary", on_click=_show_sign_in)
        return

    mode = st.segmented_control("Account", ["Sign in", "Create account", "Forgot password"],
                                key="auth_mode", selection_mode="single") or "Sign in"

    if mode == "Sign in":
        with st.form("sign_in", border=True):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary"):
                if verify_password(username.strip(), password):
                    _start_login(account_name(username.strip()) or username.strip())
                    st.rerun()
                else:
                    st.error("Incorrect username or password.")

    elif mode == "Create account":
        with st.form("create_account", border=True):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            confirmation = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create account", type="primary"):
                username = username.strip()
                error = _password_error(password, confirmation)
                if not re.fullmatch(r"[A-Za-z0-9_-]{3,30}", username):
                    st.error("Use 3-30 letters, numbers, underscores, or hyphens for the username.")
                elif account_exists(username):
                    st.error("That username already exists. Sign in or choose another one.")
                elif error:
                    st.error(error)
                else:
                    st.session_state.new_recovery_code = create_account(username, password) or ""
                    st.session_state.recovery_reason = "account"
                    st.rerun()
        st.button("Back to sign in", on_click=_show_sign_in)

    else:
        if not st.session_state.recovery_username:
            with st.form("verify_recovery", border=True):
                username = st.text_input("Username")
                recovery_code = st.text_input("Recovery code", type="password")
                if st.form_submit_button("Verify recovery code", type="primary"):
                    if verify_recovery_code(username.strip(), recovery_code):
                        st.session_state.recovery_username = username.strip()
                        st.rerun()
                    else:
                        st.error("The username or recovery code is incorrect.")
        else:
            with st.form("reset_password", border=True):
                st.write(f"Resetting password for **{st.session_state.recovery_username}**")
                password = st.text_input("New password", type="password")
                confirmation = st.text_input("Confirm new password", type="password")
                if st.form_submit_button("Reset password", type="primary"):
                    error = _password_error(password, confirmation)
                    if error:
                        st.error(error)
                    else:
                        st.session_state.new_recovery_code = reset_password(
                            st.session_state.recovery_username, password)
                        st.session_state.recovery_reason = "reset"
                        st.session_state.recovery_username = ""
                        st.rerun()
        st.button("Back to sign in", on_click=_show_sign_in)

    st.caption("Sessions last up to 14 days. This prototype uses local SQLite credentials; do not reuse an important password.")


def profile_editor(existing: dict | None) -> None:
    with st.container(border=True):
        st.subheader("Your tracking profile")
        degree_options = ["Undergraduate", "Graduate / master's", "PhD / doctorate", "Associate", "Certificate / bootcamp", "Not currently studying", "Other"]
        degree_default = degree_options.index(existing["degree"]) if existing and existing["degree"] in degree_options else 0
        degree = st.selectbox("What degree are you pursuing right now?", degree_options,
                              index=degree_default if existing else None, placeholder="e.g. Undergraduate, Graduate, etc.")
        field_options = list(FIELDS)
        field_default = field_options.index(existing["field"]) if existing and existing["field"] in field_options else 0
        field = st.selectbox("Broad field", field_options, index=field_default)
        subfield_options = FIELDS[field]
        subfield_default = subfield_options.index(existing["subfield"]) if existing and existing["subfield"] in subfield_options else 0
        subfield = st.selectbox("Specialization", subfield_options, index=subfield_default)
        keywords = st.text_input("Job keyword", value=existing.get("keywords", "") if existing else "", placeholder="e.g. machine learning intern")
        gender_options = ["Woman", "Man", "Non-binary", "Another identity", "Prefer not to say"]
        saved_gender = existing.get("gender") if existing else None
        gender_index = gender_options.index(saved_gender) if saved_gender in gender_options else None
        gender = st.selectbox("Gender (optional)", gender_options, index=gender_index,
                              placeholder="Leave blank if you prefer not to answer",
                              help="Stored with your local profile and not shown in job results or the profile summary.")
        if st.button("Save profile", type="primary", icon=":material/save:"):
            if degree is None:
                st.error("Select your current degree so jobs can be filtered automatically.")
            else:
                save_profile(st.session_state.username, degree, field, subfield, keywords.strip(), gender)
                st.session_state.editing_profile = False
                st.session_state.jobs = None
                st.rerun()


def jobs_page(p: dict) -> None:
    st.title(f"Hi {st.session_state.username}, begin tracking your career")
    query = p["keywords"] or p["subfield"]
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(f"{p['degree']} · {p['field']} · {p['subfield']} · tracking **{query}**")
        if st.button("Edit profile", icon=":material/edit:"):
            st.session_state.editing_profile = True
            st.rerun()

    with st.container(border=True):
        st.subheader("Live opportunities")
        st.caption("Current listings from Arbeitnow, Remotive, Adzuna, Greenhouse, Lever, and optional USAJOBS. Always verify details on the employer page before applying.")
        if st.button("Refresh jobs", type="primary", icon=":material/refresh:"):
            cached_jobs.clear()
            st.session_state.jobs = None

        if st.session_state.jobs is None:
            with st.spinner("Searching verified job feeds…"):
                jobs, errors = cached_jobs(query)
                st.session_state.jobs = jobs
                st.session_state.source_errors = errors
                if not jobs.empty and not errors:
                    record_snapshot(jobs, username=st.session_state.username, query=query)
        jobs = classify_jobs(st.session_state.jobs) if not st.session_state.jobs.empty else st.session_state.jobs

        if st.session_state.get("source_errors"):
            st.warning("Some sources were unavailable; results may be incomplete.")
            with st.expander("Source details"):
                for error in st.session_state.source_errors:
                    st.write(f"- {error}")
        if jobs.empty:
            st.info("No matching live roles were returned. Try a broader keyword in Edit profile.")
            historical_jobs_search(query)
            regional_job_resources(query)
            return
        if len(jobs) < 20:
            st.info("Coverage is currently small for this search. Try a broader one-word keyword, keep "
                    "'Other / unspecified' enabled for worldwide roles, and configure more Greenhouse/Lever "
                    "employer boards. A low count reflects the connected feeds, not the whole country market.")

        with st.popover("Filter jobs", icon=":material/filter_list:"):
            with st.form("job_filters", border=False):
                country_options = [*COUNTRIES, "Other / unspecified"]
                selected_countries = st.multiselect("Country", country_options, default=[], placeholder="Select",
                                                    help="Leave empty for every country. Unspecified includes worldwide/remote listings with no single country.")
                selected_sources = st.multiselect("Source", list(SOURCES), default=[], placeholder="Select",
                                                  help="Leave empty for every source.")
                job_types = st.multiselect("Employment type", sorted(jobs.job_type.dropna().unique()),
                                           default=[], placeholder="Select", help="Leave empty for every employment type.")
                workplace_types = st.multiselect("Workplace", sorted(jobs.workplace_type.dropna().unique()),
                                                 default=[], placeholder="Select", help="Leave empty for every workplace type.")
                statuses = st.multiselect("Listing status", ["Past known deadline", "Applications open soon", "Recruiting now"],
                                          default=[], placeholder="Select", help="Leave empty for every listing status.")
                new_only = st.toggle("New within one week")
                remote_only = st.toggle("Remote only")
                date_window = st.date_input("Posted between", value=(date.today() - timedelta(days=365), date.today() + timedelta(days=3650)))
                st.form_submit_button("Apply filters", type="primary", icon=":material/check:")
        filtered = jobs[jobs.status.isin(statuses)] if statuses else jobs
        filtered = filtered[filtered.country.isin(selected_countries)] if selected_countries else filtered
        filtered = filtered[filtered.source.isin(selected_sources)] if selected_sources else filtered
        filtered = filtered[filtered.job_type.isin(job_types)] if job_types else filtered
        filtered = filtered[filtered.workplace_type.isin(workplace_types)] if workplace_types else filtered
        if new_only:
            filtered = filtered[filtered.new_this_week]
        if remote_only:
            filtered = filtered[filtered.remote]
        if isinstance(date_window, tuple) and len(date_window) == 2:
            posted = pd.to_datetime(filtered.posted_at, utc=True).dt.date
            filtered = filtered[(posted >= date_window[0]) & (posted <= date_window[1])]
        filtered = filtered[filtered.degree_level.map(lambda level: degree_matches(p["degree"], level))]

        st.caption(f"Degree fit is applied automatically for **{p['degree']}**; roles without a stated requirement remain included.")
        st.dataframe(filtered[["title", "company", "country", "location", "job_type", "workplace_type", "degree_level", "posted_at", "opens_at", "deadline", "status", "source", "url"]], hide_index=True,
            column_config={"url": st.column_config.LinkColumn("Apply / details", display_text="Open listing"),
                           "job_type": "Employment type", "workplace_type": "Workplace", "degree_level": "Degree requirement",
                           "posted_at": st.column_config.DatetimeColumn("Posted", format="MMM D, YYYY"),
                           "opens_at": st.column_config.DatetimeColumn("Applications open", format="MMM D, YYYY"),
                           "deadline": st.column_config.DatetimeColumn("Known deadline", format="MMM D, YYYY")}, key="job_results")
        st.caption(f"Showing {len(filtered)} of {len(jobs)} matched roles.")
    historical_jobs_search(query)
    regional_job_resources(query)


def historical_jobs_search(default_query: str) -> None:
    with st.expander("Search ended U.S. federal recruitment"):
        st.caption("The official USAJOBS archive provides real opening and closing dates for U.S. federal announcements. It does not cover private-sector or non-U.S. roles.")
        with st.form("historic_usajobs_search"):
            query = st.text_input("Title or agency words", value=default_query)
            dates = st.date_input("Announcement opened between",
                                  value=(date.today() - timedelta(days=90), date.today()),
                                  min_value=date(2024, 1, 1), max_value=date.today())
            submitted = st.form_submit_button("Search ended announcements")
        if submitted:
            if not query.strip():
                st.error("Enter at least one title or agency word.")
            elif not isinstance(dates, tuple) or len(dates) != 2:
                st.error("Select both a start and end date.")
            else:
                with st.spinner("Searching the official USAJOBS archive…"):
                    result, note = cached_historic_jobs(query.strip(), dates[0].isoformat(), dates[1].isoformat())
                st.session_state.historic_jobs = classify_jobs(result) if not result.empty else result
                st.session_state.historic_jobs_note = note or ""
        historic = st.session_state.historic_jobs
        if historic is not None:
            if st.session_state.historic_jobs_note:
                st.caption(st.session_state.historic_jobs_note)
            if historic.empty:
                st.info("No matching federal announcements were found in the scanned archive range.")
            else:
                history_counts = (historic.assign(month=historic.opens_at.dt.strftime("%Y-%m"))
                                  .groupby("month", as_index=False).size().rename(columns={"size": "announcements"}))
                st.bar_chart(history_counts, x="month", y="announcements",
                             x_label="Application opening month", y_label="Matched announcements")
                st.dataframe(historic[["title", "company", "location", "opens_at", "deadline", "status", "url"]],
                    hide_index=True, column_config={"url": st.column_config.LinkColumn("Archived announcement", display_text="Open"),
                    "opens_at": st.column_config.DatetimeColumn("Applications opened", format="MMM D, YYYY"),
                    "deadline": st.column_config.DatetimeColumn("Applications closed", format="MMM D, YYYY")})


def regional_job_resources(query: str) -> None:
    encoded = quote_plus(query)
    slug = "-".join(re.findall(r"[A-Za-z0-9]+", query.lower())) or "jobs"
    with st.expander("More job resources for Japan and Singapore"):
        st.caption("These links open external job portals. Coverage, eligibility, language, and visa requirements differ; verify each employer listing.")
        japan, singapore = st.columns(2)
        with japan:
            st.subheader("Japan")
            resources = [
                ("Hello Work — official", "https://www.hellowork.mhlw.go.jp/"),
                ("JREC-IN — research & academic", "https://jrecin.jst.go.jp/seek/SeekTop?ln=1"),
                ("TokyoDev — international tech", "https://www.tokyodev.com/"),
                ("Japan Dev — English-friendly tech", "https://japan-dev.com/jobs"),
                ("GaijinPot Jobs", f"https://jobs.gaijinpot.com/job/index/lang/en?keywords={encoded}"),
                ("CareerCross — bilingual roles", f"https://www.careercross.com/en/job-search?keyword={encoded}"),
                ("Daijob — bilingual roles", "https://www.daijob.com/en/"),
                ("Indeed Japan", f"https://jp.indeed.com/jobs?q={encoded}"),
                ("LinkedIn Japan", f"https://www.linkedin.com/jobs/search/?keywords={encoded}&location=Japan"),
            ]
            for label, url in resources:
                st.link_button(label, url, use_container_width=True)
        with singapore:
            st.subheader("Singapore")
            resources = [
                ("MyCareersFuture — government portal", f"https://www.mycareersfuture.gov.sg/search?search={encoded}"),
                ("Careers@Gov — public service", f"https://jobs.careers.gov.sg/jobs/hrp/search?query={encoded}"),
                ("CareersHorizon — fairs & events", "https://careershorizon.mycareersfuture.gov.sg/"),
                ("LifeSG job-search support", "https://www.life.gov.sg/guides/support-for-your-job-search/find-job-opportunities"),
                ("JobStreet Singapore", f"https://sg.jobstreet.com/{slug}-jobs"),
                ("JobsDB Singapore", f"https://sg.jobsdb.com/{slug}-jobs"),
                ("Indeed Singapore", f"https://sg.indeed.com/jobs?q={encoded}"),
                ("LinkedIn Singapore", f"https://www.linkedin.com/jobs/search/?keywords={encoded}&location=Singapore"),
            ]
            for label, url in resources:
                st.link_button(label, url, use_container_width=True)


def insights_page(p: dict) -> None:
    st.title("Market movement")
    st.write("Daily snapshots show when roles enter and leave the sources you track.")
    query = p["keywords"] or p["subfield"]
    scope = st.segmented_control("Data to analyze", ["Current tracker", "All my trackers"],
                                 default="Current tracker")
    selected_query = query if scope == "Current tracker" else None
    period_type = st.segmented_control("History range", ["All available", "Week", "Month", "Year", "Custom"],
                                       default="All available")
    today = date.today()
    years = list(range(2024, today.year + 1))
    if period_type == "All available":
        first, latest = snapshot_bounds(st.session_state.username, selected_query)
        start_date = date.fromisoformat(first) if first else date(2024, 1, 1)
        end_date = date.fromisoformat(latest) if latest else today
    elif period_type == "Week":
        selected_year = st.selectbox("Year", years, index=len(years) - 1, key="insight_week_year")
        max_week = date(selected_year, 12, 28).isocalendar().week
        default_week = min(today.isocalendar().week, max_week) if selected_year == today.year else 1
        def week_label(week: int) -> str:
            monday = date.fromisocalendar(selected_year, week, 1)
            sunday = date.fromisocalendar(selected_year, week, 7)
            return f"{monday:%b %d, %Y} – {sunday:%b %d, %Y}"
        selected_week = st.selectbox("Week dates (Monday–Sunday)", list(range(1, max_week + 1)),
                                     index=default_week - 1, format_func=week_label)
        start_date = date.fromisocalendar(selected_year, selected_week, 1)
        end_date = date.fromisocalendar(selected_year, selected_week, 7)
    elif period_type == "Month":
        selected_year = st.selectbox("Year", years, index=len(years) - 1, key="insight_month_year")
        selected_month = st.selectbox("Month", list(range(1, 13)),
                                      index=(today.month - 1 if selected_year == today.year else 0),
                                      format_func=lambda month: calendar.month_name[month])
        start_date = date(selected_year, selected_month, 1)
        end_date = date(selected_year, selected_month, calendar.monthrange(selected_year, selected_month)[1])
    elif period_type == "Year":
        selected_year = st.selectbox("Year", years, index=len(years) - 1, key="insight_year")
        start_date, end_date = date(selected_year, 1, 1), date(selected_year, 12, 31)
    else:
        selected_range = st.date_input("Date range", value=(date(2024, 1, 1), today),
                                       min_value=date(2024, 1, 1), max_value=today)
        if isinstance(selected_range, tuple) and len(selected_range) == 2:
            start_date, end_date = selected_range
        else:
            start_date = end_date = selected_range[0] if isinstance(selected_range, tuple) else selected_range
    st.caption(f"Selected period: **{start_date:%b %d, %Y} – {end_date:%b %d, %Y}**")
    granularity = st.segmented_control("Group chart points by", ["Day", "Week", "Month", "Year"],
                                       default="Month" if period_type == "All available" else "Day")
    chart_kind = st.segmented_control("Chart", ["New vs disappeared", "Market size", "Share of activity"], default="New vs disappeared")
    data = trend_between(start_date.isoformat(), end_date.isoformat(),
                         st.session_state.username, selected_query)
    if not data.empty and granularity != "Day":
        frequency = {"Week": "W-SUN", "Month": "ME", "Year": "YE"}[granularity]
        data = (data.set_index("date").resample(frequency)
                .agg({"new jobs": "sum", "disappeared jobs": "sum", "market jobs": "last"})
                .dropna(subset=["market jobs"]).reset_index())
    if data.empty or len(data) < 2:
        first, latest = snapshot_bounds(st.session_state.username, selected_query)
        coverage = f" Available observations run from {first} to {latest}." if first else " This tracker has no saved observations yet."
        st.info("No meaningful trend exists for the selected period; two or more observation dates are needed." + coverage)
    else:
        first_market, latest_market = int(data["market jobs"].iloc[0]), int(data["market jobs"].iloc[-1])
        metric_columns = st.columns(4)
        metric_columns[0].metric("Observation days", len(data))
        metric_columns[1].metric("New listings", int(data["new jobs"].sum()))
        metric_columns[2].metric("Disappeared listings", int(data["disappeared jobs"].sum()))
        metric_columns[3].metric("Latest market size", latest_market, latest_market - first_market)
        if chart_kind == "New vs disappeared":
            long = data.melt("date", value_vars=["new jobs", "disappeared jobs"], var_name="movement", value_name="jobs")
            st.altair_chart(alt.Chart(long).mark_line(point=True).encode(x=alt.X("date:T", title="Date"), y=alt.Y("jobs:Q", title="Jobs"), color="movement:N", tooltip=["date:T", "movement:N", "jobs:Q"]))
        elif chart_kind == "Market size":
            st.area_chart(data, x="date", y="market jobs", x_label="Date", y_label="Active listings")
        else:
            share = data.copy()
            total = share["new jobs"] + share["disappeared jobs"]
            share["new %"] = (share["new jobs"] / total.where(total > 0) * 100).fillna(0)
            share["disappeared %"] = 100 - share["new %"]
            st.area_chart(share, x="date", y=["new %", "disappeared %"], stack="normalize", x_label="Date", y_label="Share of daily movement")

    breakdown = tracker_breakdown_between(start_date.isoformat(), end_date.isoformat(),
                                          st.session_state.username, selected_query)
    st.subheader("Coverage tracker")
    if breakdown.empty:
        st.info("Source and country coverage will appear after the first search snapshot.")
    else:
        latest = breakdown[breakdown.date == breakdown.date.max()]
        source_counts = latest.groupby("source", as_index=False).jobs.sum()
        country_counts = latest.groupby("country", as_index=False).jobs.sum()
        left, right = st.columns(2)
        left.bar_chart(source_counts, x="source", y="jobs", x_label="Source", y_label="Observed listings")
        right.bar_chart(country_counts, x="country", y="jobs", x_label="Country", y_label="Observed listings")
        source_history = breakdown.groupby(["date", "source"], as_index=False).jobs.sum()
        country_history = breakdown.groupby(["date", "country"], as_index=False).jobs.sum()
        with st.expander("Source and country trends across this period"):
            st.altair_chart(alt.Chart(source_history).mark_line(point=True).encode(
                x=alt.X("date:T", title="Date"), y=alt.Y("jobs:Q", title="Observed listings"),
                color=alt.Color("source:N", title="Source"), tooltip=["date:T", "source:N", "jobs:Q"]))
            st.altair_chart(alt.Chart(country_history).mark_line(point=True).encode(
                x=alt.X("date:T", title="Date"), y=alt.Y("jobs:Q", title="Observed listings"),
                color=alt.Color("country:N", title="Country"), tooltip=["date:T", "country:N", "jobs:Q"]))
        st.caption(f"Latest coverage snapshot: {latest.date.max()} · {int(latest.jobs.sum())} listings observed.")

    raw = snapshot_rows_between(start_date.isoformat(), end_date.isoformat(),
                                st.session_state.username, selected_query)
    st.subheader("Analysis data")
    if raw.empty:
        st.caption("No rows are available to inspect or download for this selection.")
    else:
        st.caption(f"{len(raw):,} stored observations. The same listing can appear on multiple dates or trackers.")
        with st.expander("Inspect all observation rows"):
            st.dataframe(raw, hide_index=True, width="stretch",
                         column_config={"url": st.column_config.LinkColumn("Listing")})
        download_left, download_right = st.columns(2)
        download_left.download_button("Download daily trend CSV", data.to_csv(index=False),
                                      file_name=f"career-trend-{start_date}-{end_date}.csv", mime="text/csv")
        download_right.download_button("Download all observations CSV", raw.to_csv(index=False),
                                       file_name=f"career-observations-{start_date}-{end_date}.csv", mime="text/csv")
    st.caption("Scope: listings observed by this deployment—not the entire labor market. Import archived snapshots for longer retrospective coverage.")
    with st.expander("Official historical references for 2024–2025"):
        st.write("These are national statistics and archives, not interchangeable with this tracker's provider snapshots:")
        st.markdown("""
- [United States: USAJOBS historical federal announcements](https://developer.usajobs.gov/tutorials/past-job-announcements)
- [United Kingdom: ONS vacancy time series](https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/timeseries/ap2y/unem)
- [Japan: MHLW employment and job-opening indicators](https://www.mhlw.go.jp/toukei/list/114-1d.html)
- [Singapore: Ministry of Manpower job-vacancy statistics](https://stats.mom.gov.sg/Statistics/Pages/job-vacancy.aspx)
""")


def alerts_page(p: dict) -> None:
    st.title("Daily phone alerts")
    st.write("A scheduled worker checks the tracked query every day and sends new roles by SMS when Twilio is configured.")
    existing = subscription(st.session_state.username)
    with st.form("subscribe", border=True):
        phone = st.text_input("Mobile number", value=existing["phone"] if existing else "",
                              placeholder="+81…", help="Use E.164 format, including country code.")
        consent = st.checkbox("I agree to receive daily job alerts and understand carrier messaging rates may apply.")
        submitted = st.form_submit_button("Subscribe", type="primary", icon=":material/notifications_active:")
        if submitted:
            if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
                st.error("Enter a valid E.164 number, such as +819012345678.")
            elif not consent:
                st.error("Consent is required for SMS alerts.")
            else:
                save_subscription(st.session_state.username, phone, p["keywords"] or p["subfield"])
                st.success("Subscribed. Alerts send after the scheduler and Twilio secrets are enabled.")
    if existing and existing["enabled"]:
        st.caption(f"Alerts are active for **{existing['query']}**. Consent recorded {existing['consented_at'] or 'before consent timestamps were added'}.")
        if st.button("Unsubscribe from SMS alerts", icon=":material/notifications_off:"):
            disable_subscription(st.session_state.username)
            st.success("SMS alerts disabled.")
            st.rerun()
    st.caption("Reply handling and STOP compliance must be configured in Twilio before a public launch.")


def chat_page(p: dict) -> None:
    st.title("Career coach")
    st.subheader("Want to discover what jobs are the best fit for you?")
    st.write("Share your university, classes, interests, target location, or a role you’re considering. None are required.")
    if not st.session_state.messages:
        suggestion = st.pills("Try asking", ["What fits my degree?", "Skills for a data analyst", "Help me explore careers"], label_visibility="collapsed")
        if suggestion:
            st.session_state.messages.append({"role": "user", "content": suggestion})
            st.rerun()
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    if prompt := st.chat_input("Tell me about you or ask about a job", submit_mode="disable"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        skills = suggested_skills(prompt)
        answer = (f"Based on what you shared, start by exploring **{p['subfield']}** roles and compare them with the keywords in current postings. "
                  f"Common skills to build: **{', '.join(skills)}**.\n\n"
                  "Reliable next steps: [O*NET occupation and skills profiles](https://www.onetonline.org/), "
                  "[U.S. Bureau of Labor Statistics Occupational Outlook Handbook](https://www.bls.gov/ooh/), and the live listings on your Jobs page. "
                  "These sources support exploration; confirm requirements in each employer’s official listing.")
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.rerun()


def about_page() -> None:
    st.title("About Career Compass")
    st.write("Career Compass is a learning-focused job discovery and market-tracking prototype.")
    st.subheader("What it can do")
    st.markdown("""
- Search and normalize current listings from Arbeitnow, Remotive, configured Adzuna/Greenhouse/Lever, and optional USAJOBS sources.
- Search ended U.S. federal announcements in the public USAJOBS archive using real opening and closing dates.
- Filter roles by country, source, employment type, workplace type, date, inferred listing status, and degree fit.
- Save a personal tracking profile, build daily listing snapshots, show observed market movement, and prepare SMS alerts when Twilio is configured.
- Offer basic career-exploration prompts and links to external occupational resources.
""")
    st.subheader("Important limitations")
    st.markdown("""
- Results are only the listings observed from configured feeds. They are not the complete job market and country coverage can be uneven.
- Japan and China currently depend mainly on configured Greenhouse/Lever employer boards and matching global listings. Adzuna coverage in this app targets Singapore, the US, and the UK.
- The five-year chart does not create historical data. It shows only snapshots actually collected by this deployment; genuine past coverage needs licensed or imported historical data.
- Employment type, country, degree fit, and listing status may be inferred when providers do not supply structured values. Always confirm details on the employer page.
- "Applications open soon" appears only when a provider supplies a future application-opening date; the app does not predict unpublished recruitment.
- The career coach is rule-based guidance, not professional career advice. SMS alerts require separate Twilio setup and compliance work.
- Credentials are stored in local SQLite using salted password hashes. This is appropriate for a prototype, but a public production service should use a managed identity provider, hosted database, rate limiting, audit logs, and HTTPS.
""")
    st.info("If both your password and recovery code are lost, the account cannot be recovered. Accounts are never deleted automatically.")


def _set_account_view(view: str | None) -> None:
    st.session_state.account_view = view


def _log_out() -> None:
    end_session(st.session_state.session_token)
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.session_token = ""
    st.session_state.jobs = None
    st.session_state.messages = []
    st.session_state.account_view = None
    st.session_state.browser_session_action = "clear"
    st.session_state.browser_session_checked = True
    st.session_state.welcome_back = False


def _switch_to(username: str) -> None:
    end_session(st.session_state.session_token)
    st.session_state.username = username
    st.session_state.session_token = create_session(username)
    st.session_state.browser_session_action = "save"
    st.session_state.jobs = None
    st.session_state.messages = []
    st.session_state.account_view = None
    st.session_state.welcome_back = True


def _finish_added_account() -> None:
    username = st.session_state.added_account_name
    st.session_state.added_recovery_code = ""
    st.session_state.added_account_name = ""
    _switch_to(username)


def account_view() -> None:
    if st.session_state.account_view == "switch":
        st.title("Switch account")
        accounts = linked_accounts(st.session_state.username)
        if not accounts:
            st.info("No other accounts are linked yet. Use Add account to create a new one or link an existing one.")
        for username in accounts:
            st.button(f"Switch to {username}", key=f"switch_{username}",
                      on_click=_switch_to, args=(username,), icon=":material/switch_account:")
        st.button("Cancel and return to the app", on_click=_set_account_view, args=(None,))
        return

    if st.session_state.account_view == "delete":
        st.title("Delete account")
        st.warning("This permanently deletes your account, profile, alert subscription, sessions, and tracked snapshots.")
        with st.form("delete_account"):
            password = st.text_input("Confirm your password", type="password")
            confirmed = st.checkbox("I understand this cannot be undone")
            if st.form_submit_button("Permanently delete account", type="primary"):
                if not verify_password(st.session_state.username, password):
                    st.error("Incorrect password.")
                elif not confirmed:
                    st.error("Confirm that you understand the deletion is permanent.")
                else:
                    username = st.session_state.username
                    delete_account(username)
                    _log_out()
                    st.rerun()
        st.button("Cancel and return to the app", on_click=_set_account_view, args=(None,))
        return

    st.title("Add account")
    if st.session_state.added_recovery_code:
        st.success(f"Account **{st.session_state.added_account_name}** created and linked.")
        st.write("Save this recovery code now; it will not be shown again.")
        st.code(st.session_state.added_recovery_code, language=None)
        st.warning("If both the password and recovery code are lost, this account cannot be recovered.")
        st.button("I saved it — switch to the new account", type="primary",
                  on_click=_finish_added_account)
        return

    add_mode = st.segmented_control("Account type", ["Create new account", "Link existing account"],
                                    default="Create new account")
    if add_mode == "Create new account":
        st.write("Create a separate account. It will be linked to the current account for easy switching.")
        with st.form("create_linked_account", border=True):
            username = st.text_input("New username")
            password = st.text_input("New password", type="password")
            confirmation = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Create and add account", type="primary"):
                username = username.strip()
                error = _password_error(password, confirmation)
                if not re.fullmatch(r"[A-Za-z0-9_-]{3,30}", username):
                    st.error("Use 3-30 letters, numbers, underscores, or hyphens for the username.")
                elif account_exists(username):
                    st.error("That username already exists. Choose another or use Link existing account.")
                elif error:
                    st.error(error)
                else:
                    recovery_code = create_account(username, password)
                    if recovery_code:
                        stored_username = account_name(username) or username
                        link_accounts(st.session_state.username, stored_username)
                        st.session_state.added_account_name = stored_username
                        st.session_state.added_recovery_code = recovery_code
                        st.rerun()
                    else:
                        st.error("The account could not be created. Choose another username.")
    else:
        st.write("Sign in to an account that already exists. Its password is checked once before linking.")
        with st.form("link_account", border=True):
            username = st.text_input("Existing account username")
            password = st.text_input("Existing account password", type="password")
            if st.form_submit_button("Verify and link existing account", type="primary"):
                username = username.strip()
                if username.casefold() == st.session_state.username.casefold():
                    st.error("This is already the current account.")
                elif verify_password(username, password):
                    stored_username = account_name(username) or username
                    link_accounts(st.session_state.username, stored_username)
                    st.success(f"{stored_username} is linked. You can now switch accounts from the account menu.")
                else:
                    st.error("Incorrect username or password. The account was not linked.")
    st.button("Cancel and return to the app", on_click=_set_account_view, args=(None,))


if not st.session_state.logged_in:
    login()
    st.stop()

if st.session_state.welcome_back:
    st.toast(f"Welcome back {st.session_state.username}!", icon=":material/waving_hand:")
    st.session_state.welcome_back = False

p = profile(st.session_state.username)
if p is None or st.session_state.editing_profile:
    profile_editor(p)
    st.stop()

with st.sidebar:
    st.header("Career compass")
    page = st.segmented_control("Navigate", ["Jobs", "Insights", "Alerts", "Career coach", "About"],
                                key="active_page", selection_mode="single") or "Jobs"
    st.divider()
    with st.popover(st.session_state.username, icon=":material/account_circle:", width="stretch"):
        st.caption("Account menu")
        st.button("Switch account", width="stretch", icon=":material/switch_account:",
                  on_click=_set_account_view, args=("switch",))
        st.button("Add account", width="stretch", icon=":material/person_add:",
                  on_click=_set_account_view, args=("add",))
        st.button("Log out", width="stretch", icon=":material/logout:", on_click=_log_out)
        st.button("Delete account", width="stretch", icon=":material/delete:",
                  on_click=_set_account_view, args=("delete",))

if st.session_state.account_view:
    account_view()
else:
    {"Jobs": jobs_page, "Insights": insights_page, "Alerts": alerts_page,
     "Career coach": chat_page, "About": lambda _: about_page()}[page](p)
