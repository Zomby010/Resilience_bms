"""GPS tracking: work sites, working hours, location updates and alerts.

Coordinates are WGS84 latitude/longitude in decimal degrees (what phones give).
Distances are worked out on the server in `geo.py`; the browser never decides
whether someone is on location.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

# Geofence boundaries (metres). See geo.classify() for the full rule.
NEAR_LIMIT_M = 50          # past the site radius but within this = NEAR LOCATION; beyond = OFF LOCATION
MAX_ACCURACY_M = 50        # readings less accurate than this are GPS WEAK, never OFF
SIGNAL_LOST_AFTER_S = 300  # no update for 5 minutes while tracking = SIGNAL LOST
MIN_UPDATE_INTERVAL_S = 10  # server refuses updates more often than this
HISTORY_DAYS = 90          # location history older than this is deleted


class LocationStatus(models.TextChoices):
    ON = "on", "On location"
    NEAR = "near", "Near location"
    OFF = "off", "Off location"
    WEAK = "weak", "GPS weak"
    # The states below are never stored on a ping; they are worked out when shown.
    WAITING = "waiting", "Waiting for GPS"
    SIGNAL_LOST = "lost", "Signal lost"
    TRACKING_OFF = "tracking_off", "Tracking off"
    NO_SITE = "no_site", "No site assigned"


class SiteColour(models.TextChoices):
    """Eight colours that colour-blind people can still tell apart (Okabe-Ito). Always shown with the site name."""

    BLUE = "blue", "Blue"
    ORANGE = "orange", "Orange"
    GREEN = "green", "Green"
    PURPLE = "purple", "Pink-purple"
    SKY = "sky", "Sky blue"
    RED = "red", "Red-orange"
    YELLOW = "yellow", "Yellow"
    BLACK = "black", "Black"


SITE_COLOUR_HEX = {"blue": "#0072B2", "orange": "#E69F00", "green": "#009E73", "purple": "#CC79A7",
                   "sky": "#56B4E9", "red": "#D55E00", "yellow": "#F0E442", "black": "#000000"}


def next_site_colour():
    """The colour fewest sites use, so new sites look different from the others."""
    used = dict(Site.objects.values("colour").annotate(n=models.Count("id")).values_list("colour", "n"))
    return min(SiteColour.values, key=lambda c: used.get(c, 0))


class Site(models.Model):
    """A place guards are posted to, e.g. "Kondele Site"."""

    name = models.CharField(max_length=120, unique=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )
    radius_m = models.PositiveSmallIntegerField(
        "on-location radius (metres)",
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(NEAR_LIMIT_M)],
        help_text=f"How close counts as ON LOCATION. Between 5 and {NEAR_LIMIT_M} metres. 30 suits most sites.",
    )
    is_active = models.BooleanField(default=True)
    colour = models.CharField(
        max_length=10, choices=SiteColour.choices, blank=True,
        help_text="Shown as a stripe on this site's OB entries, always with its name. Picked automatically; change it if two sites look alike.",
    )
    # Site details: edited by the Manager and Secretary, read-only for supervisors and staff.
    address = models.CharField("address / directions", max_length=255, blank=True)
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="supervised_sites",
        limit_choices_to={"role": "supervisor"}, help_text="The supervisor who looks after this site.",
    )
    guards_needed = models.PositiveSmallIntegerField(
        "guards needed per shift", default=1, help_text="Fewer guards available than this shows the site as SHORT-STAFFED.",
    )
    instructions = models.TextField("site instructions", blank=True, help_text="What guards must do at this site.")
    emergency_contacts = models.TextField(
        blank=True, help_text="One per line, for example: Kondele Police Post 0712 000 000.",
    )
    details_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    details_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.colour:
            self.colour = next_site_colour()
        super().save(*args, **kwargs)

    @property
    def colour_hex(self):
        return SITE_COLOUR_HEX.get(self.colour, "#52606f")

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("operations:site_detail", args=[self.pk])


def hours_summary(rows):
    """A week of WorkHours rows in one line: "Mon–Sat 07:00–18:00, Sun off". A day with no row is a day off."""
    days = {r.weekday: f"{r.start:%H:%M}–{r.end:%H:%M}" for r in rows}
    if not days:
        return "Not set"
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    runs = []  # [first day, last day, hours or None for off]
    for d in range(7):
        h = days.get(d)
        if runs and runs[-1][2] == h:
            runs[-1][1] = d
        else:
            runs.append([d, d, h])
    parts = []
    for first, last, h in runs:
        span = names[first] if first == last else f"{names[first]}–{names[last]}"
        parts.append(f"{span} {h or 'off'}")
    return ", ".join(parts)


class TrackingProfile(models.Model):
    """One row per staff member or supervisor: their site and their latest known state."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracking")
    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.SET_NULL, related_name="people")
    own_hours = models.BooleanField(
        default=False, help_text="Use this person's own working hours instead of the site's."
    )

    tracking_on = models.BooleanField(default=False)
    tracking_changed_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, help_text="Last time the person used the site.")

    # Latest accepted location (a copy of the newest ping, so dashboards need no history scan).
    last_ping_at = models.DateTimeField(null=True, blank=True)
    last_latitude = models.FloatField(null=True, blank=True)
    last_longitude = models.FloatField(null=True, blank=True)
    last_accuracy_m = models.FloatField(null=True, blank=True)
    last_distance_m = models.FloatField(null=True, blank=True)
    last_status = models.CharField(max_length=20, choices=LocationStatus.choices, blank=True)

    def __str__(self):
        return f"Tracking for {self.user}"


class WorkHours(models.Model):
    """One working day for a site (or for one person, when they have their own hours).

    An end time earlier than the start time means the shift runs past midnight,
    e.g. 18:00 to 06:00. A day with no row is a day off.
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.CASCADE, related_name="hours")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="work_hours"
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start = models.TimeField()
    end = models.TimeField()

    class Meta:
        ordering = ["weekday"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(site__isnull=False, user__isnull=True) | Q(site__isnull=True, user__isnull=False)),
                name="workhours_site_xor_user",
            ),
            models.UniqueConstraint(fields=["site", "weekday"], name="workhours_one_per_site_day"),
            models.UniqueConstraint(fields=["user", "weekday"], name="workhours_one_per_user_day"),
        ]

    def clean(self):
        if self.start == self.end:
            raise ValidationError("Start and end time cannot be the same.")

    @property
    def overnight(self):
        return self.end < self.start

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start:%H:%M}-{self.end:%H:%M}"


class LocationPing(models.Model):
    """Every location update received (history). Kept for HISTORY_DAYS days."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="location_pings")
    received_at = models.DateTimeField(db_index=True, help_text="Server time the update arrived.")
    measured_at = models.DateTimeField(help_text="Time the phone took the reading.")
    latitude = models.FloatField()
    longitude = models.FloatField()
    accuracy_m = models.FloatField()
    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    distance_m = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=LocationStatus.choices, blank=True)
    flag = models.CharField(max_length=120, blank=True, help_text="Why this reading looks wrong, if it does.")

    class Meta:
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["user", "-received_at"])]

    def __str__(self):
        return f"{self.user} at {self.received_at:%Y-%m-%d %H:%M}"


class Alert(models.Model):
    """Something the manager should look at. Closes itself when the problem goes away."""

    class Kind(models.TextChoices):
        OFF_LOCATION = "off_location", "Off location"
        TRACKING_OFF = "tracking_off", "Location not turned on"
        SIGNAL_LOST = "signal_lost", "Location updates stopped"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="location_alerts")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    message = models.CharField(max_length=200)
    created_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind"], condition=Q(resolved_at__isnull=True), name="one_open_alert_per_kind"
            )
        ]

    def __str__(self):
        return self.message


class SitePosting(models.Model):
    """History of who was posted to which site, and when. Written whenever a person's site changes."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="postings")
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="postings")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user"], condition=Q(ended_at__isnull=True), name="one_current_posting_per_person")
        ]

    def __str__(self):
        return f"{self.user} at {self.site}"


class AuditEntry(models.Model):
    """Who changed which location setting, and when."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "audit entries"

    def __str__(self):
        return f"{self.actor}: {self.action}"
