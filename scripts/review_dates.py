"""The shared calendar-date allowance for source-review metadata."""
import datetime as dt


def review_date_is_future(reviewed, now):
    """Allow tomorrow's UTC date for reviewers whose local calendar is ahead.

    Callers validate the date syntax. Publication dates stay strict, and precise
    review timestamps keep their separate 24-hour comparison.
    """
    return reviewed > now.astimezone(dt.timezone.utc).date() + dt.timedelta(days=1)
