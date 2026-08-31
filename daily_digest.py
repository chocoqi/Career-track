"""Run once daily via Task Scheduler, cron, or the included GitHub Actions workflow."""
import os

from career_data import (fetch_jobs, mark_jobs_delivered, record_snapshot,
                         subscriptions, undelivered_jobs)


def send_sms(to: str, body: str) -> None:
    from twilio.rest import Client
    Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]).messages.create(
        body=body, from_=os.environ["TWILIO_FROM_NUMBER"], to=to
    )


for subscription in subscriptions():
    username, query = subscription["username"], subscription["query"]
    try:
        jobs, errors = fetch_jobs(query, limit=20)
        if jobs.empty:
            if errors:
                print(f"{username}: providers unavailable; no alert sent")
            continue
        if not errors:
            record_snapshot(jobs, username=username, query=query)
        unseen = undelivered_jobs(username, jobs)
        if unseen.empty:
            continue
        newest = unseen.head(3)
        lines = [f"{row.title} — {row.company}: {row.url}" for row in newest.itertuples()]
        send_sms(subscription["phone"], "Career compass new jobs\n" + "\n".join(lines))
        # Treat the successful fetch as the new baseline so old overflow roles are
        # not presented as newly discovered on tomorrow's run.
        mark_jobs_delivered(username, jobs.id)
    except Exception as exc:
        # A provider or Twilio failure for one account must not block the others.
        print(f"{username}: daily alert failed: {exc}")
