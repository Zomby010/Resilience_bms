import re
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from core.testing import OpsTestCase
from core.workflow import TransitionError
from notifications.models import Notification

from . import services
from .models import Item, ItemRequest, StockMovement

R = ItemRequest.Status


def strip_tokens(html):
    """Remove random CSRF tokens so number checks can't match them by chance."""
    return re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', "", html)


def counts(item):
    item.refresh_from_db()
    return item.quantities()


class StockTests(OpsTestCase):
    def test_create_item_gives_code_and_opening_ledger_row(self):
        item = services.create_item(Item(name="Radio", category=self.category, returnable=True), 4, self.secretary)
        self.assertEqual(item.code, f"ITM-{item.pk:04d}")
        self.assertEqual(counts(item)["qty_available"], 4)
        mv = item.movements.get()
        self.assertEqual((mv.action, mv.quantity, mv.before["qty_available"], mv.after["qty_available"]), ("added", 4, 0, 4))

    def test_adjustments_write_one_ledger_row_each(self):
        services.adjust_stock(self.item, "damaged", 2, "Dropped", self.secretary)
        services.adjust_stock(self.item, "repaired", 1, "Fixed", self.secretary)
        services.adjust_stock(self.item, "write_off_damaged", 1, "Beyond repair", self.secretary)
        services.adjust_stock(self.item, "add", 3, "Delivery", self.secretary)
        c = counts(self.item)
        self.assertEqual((c["qty_available"], c["qty_damaged"]), (7, 0))
        self.assertEqual(self.item.movements.count(), 4)
        self.assertTrue(Notification.objects.filter(recipient=self.manager, kind="item.damaged").exists())

    def test_never_below_zero(self):
        with self.assertRaisesMessage(TransitionError, "Not enough stock"):
            services.adjust_stock(self.item, "write_off", 6, "Too many", self.secretary)
        self.assertEqual(counts(self.item)["qty_available"], 5)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_reason_required(self):
        with self.assertRaises(TransitionError):
            services.adjust_stock(self.item, "add", 1, "  ", self.secretary)

    def test_low_stock_notified_once_per_drop(self):
        Item.objects.filter(pk=self.item.pk).update(min_stock=3)
        self.item.refresh_from_db()
        services.adjust_stock(self.item, "write_off", 2, "x", self.secretary)  # 3 left
        services.adjust_stock(self.item, "write_off", 1, "x", self.secretary)  # 2 left
        self.assertEqual(Notification.objects.filter(kind="item.low_stock", recipient=self.secretary).count(), 1)
        services.adjust_stock(self.item, "add", 5, "x", self.secretary)        # back above
        services.adjust_stock(self.item, "write_off", 4, "x", self.secretary)  # low again
        self.assertEqual(Notification.objects.filter(kind="item.low_stock", recipient=self.secretary).count(), 2)

    def test_cannot_retire_item_with_open_requests(self):
        with self.assertRaises(TransitionError):
            services.set_item_active(self.item, False, self.secretary)

    def test_ledger_matches_counts_after_a_full_cycle(self):
        req = self.req_a1
        services.approve_request(req, self.secretary, 1, self.later)
        services.hand_over(req, self.secretary)
        services.claim_return(req, self.staff_a1)
        services.approve_return(req, self.secretary, 1, 0, 0)
        c = counts(self.item)
        self.assertEqual(c, {"qty_available": 5, "qty_reserved": 0, "qty_issued": 0, "qty_damaged": 0, "qty_lost": 0})
        last = self.item.movements.first()
        self.assertEqual(last.after, c)


class ManagerFlagTests(OpsTestCase):
    def test_only_manager_sets_flags(self):
        url = reverse("inventory:flags")
        self.login(self.secretary)
        self.assertEqual(self.client.post(url, {"flagged": [self.item.pk]}).status_code, 403)
        self.item.refresh_from_db()
        self.assertFalse(self.item.needs_manager_approval)
        self.login(self.manager)
        self.client.post(url, {"flagged": [self.item.pk]})
        self.item.refresh_from_db()
        self.assertTrue(self.item.needs_manager_approval)
        self.assertEqual(self.item.flag_changed_by, self.manager)
        # NOTE-01: a settings change is not news for the Secretary (it is in the audit log).
        self.assertFalse(Notification.objects.filter(recipient=self.secretary, kind="item.flags_changed").exists())
        self.client.post(url, {})
        self.item.refresh_from_db()
        self.assertFalse(self.item.needs_manager_approval)

    def test_secretary_edit_form_cannot_change_flag(self):
        self.login(self.secretary)
        self.client.post(reverse("inventory:edit", args=[self.item.pk]), {
            "name": "Torch", "category": self.category.pk, "min_stock": 0, "returnable": "on", "needs_manager_approval": "on",
        })
        self.item.refresh_from_db()
        self.assertFalse(self.item.needs_manager_approval)

    def test_flagged_item_goes_to_manager_first(self):
        Item.objects.filter(pk=self.item.pk).update(needs_manager_approval=True)
        self.item.refresh_from_db()
        req = services.create_request(self.item, 1, "Need one", self.staff_a2)
        self.assertEqual(req.status, R.AWAITING_MANAGER)
        with self.assertRaises(TransitionError):
            services.approve_request(req, self.secretary, 1, self.later)
        with self.assertRaises(TransitionError):
            services.manager_decide(req, self.secretary, True)
        services.manager_decide(req, self.manager, True)
        self.assertEqual(req.status, R.PENDING)
        services.approve_request(req, self.secretary, 1, self.later)
        self.assertEqual(req.status, R.READY)


class RequestFlowTests(OpsTestCase):
    def test_request_page_always_uses_signed_in_user(self):
        self.login(self.staff_a2)
        resp = self.client.post(reverse("inventory:request_new", args=[self.item.pk]),
                                {"qty": 2, "reason": "Night shift", "requester": self.staff_b1.pk})
        req = ItemRequest.objects.latest("id")
        self.assertRedirects(resp, reverse("inventory:request_sent", args=[req.pk]))
        self.assertEqual(req.requester, self.staff_a2)
        self.assertContains(self.client.get(resp["Location"]), "Item request sent")

    def test_quantity_limits(self):
        for qty in (0, 21):
            with self.assertRaises(TransitionError):
                services.create_request(self.item, qty, "x", self.staff_a1)

    def test_approve_reserves_then_handover_issues(self):
        services.approve_request(self.req_a1, self.secretary, 1, self.later)
        self.assertEqual((counts(self.item)["qty_available"], self.item.qty_reserved), (4, 1))
        services.hand_over(self.req_a1, self.secretary)
        self.assertEqual((self.item.qty_reserved, counts(self.item)["qty_issued"]), (0, 1))
        self.assertEqual(self.req_a1.status, R.ISSUED)

    def test_hand_over_now(self):
        services.approve_request(self.req_a1, self.secretary, 1, self.later, hand_over_now=True)
        self.assertEqual(counts(self.item)["qty_issued"], 1)
        self.assertEqual(self.req_a1.status, R.ISSUED)

    def test_cancel_approval_releases_stock(self):
        services.approve_request(self.req_a1, self.secretary, 1, self.later)
        services.cancel_approval(self.req_a1, self.secretary, "Not collected")
        self.assertEqual(counts(self.item)["qty_available"], 5)
        self.assertEqual(self.req_a1.status, R.CANCELLED)

    def test_returnable_needs_future_return_date(self):
        with self.assertRaises(TransitionError):
            services.approve_request(self.req_a1, self.secretary, 1, None)
        with self.assertRaises(TransitionError):
            services.approve_request(self.req_a1, self.secretary, 1, self.today - timedelta(days=1))

    def test_double_click_applied_once(self):
        stale = ItemRequest.objects.get(pk=self.req_a1.pk)
        services.approve_request(self.req_a1, self.secretary, 1, self.later)
        with self.assertRaisesMessage(TransitionError, "already"):
            services.approve_request(stale, self.manager, 1, self.later)
        self.assertEqual(counts(self.item)["qty_reserved"], 1)
        self.assertEqual(StockMovement.objects.filter(action="reserved").count(), 1)

    def test_two_approvals_racing_for_the_last_item(self):
        Item.objects.filter(pk=self.item.pk).update(qty_available=1)
        other = services.create_request(self.item, 1, "Need it too", self.staff_a2)
        first, second = ItemRequest.objects.get(pk=self.req_a1.pk), ItemRequest.objects.get(pk=other.pk)
        services.approve_request(first, self.secretary, 1, self.later)
        with self.assertRaisesMessage(TransitionError, "Not enough stock"):
            services.approve_request(second, self.manager, 1, self.later)
        second.refresh_from_db()
        self.assertEqual(second.status, R.PENDING)  # the status change was rolled back with the stock failure
        self.assertEqual(counts(self.item), {"qty_available": 0, "qty_reserved": 1, "qty_issued": 0, "qty_damaged": 0, "qty_lost": 0})

    def test_nobody_approves_their_own_request(self):
        req = ItemRequest.objects.create(requester=self.secretary, requester_role="secretary", item=self.item,
                                         qty_requested=1, reason="x")
        with self.assertRaisesMessage(TransitionError, "own request"):
            services.approve_request(req, self.secretary, 1, self.later)
        services.approve_request(req, self.manager, 1, self.later, hand_over_now=True)
        with self.assertRaisesMessage(TransitionError, "own request"):
            services.approve_return(req, self.secretary, 1, 0, 0)

    def test_requester_cancel_only_while_pending(self):
        services.cancel_by_requester(self.req_a1, self.staff_a1)
        self.assertEqual(self.req_a1.status, R.CANCELLED)
        with self.assertRaises(TransitionError):
            services.cancel_by_requester(self.req_a1, self.staff_a1)

    def test_requester_pages_show_no_stock_counts(self):
        Item.objects.filter(pk=self.item.pk).update(qty_available=4817)
        self.login(self.staff_a1)
        page = strip_tokens(self.client.get(reverse("inventory:browse")).content.decode())
        self.assertIn("Available", page)
        self.assertNotIn("4817", page)


class ReturnRuleTests(OpsTestCase):
    """The physical return rule."""

    def issue(self, qty=1):
        services.approve_request(self.req_a1, self.secretary, qty, self.later, hand_over_now=True)

    def test_claim_changes_status_only(self):
        self.issue()
        before = counts(self.item)
        n = StockMovement.objects.count()
        self.login(self.staff_a1)
        self.client.post(reverse("inventory:mine_returned", args=[self.req_a1.pk]))
        self.req_a1.refresh_from_db()
        self.assertEqual(self.req_a1.status, R.RETURN_CLAIMED)
        self.assertEqual(counts(self.item), before)
        self.assertEqual(StockMovement.objects.count(), n)

    def test_staff_and_supervisors_cannot_approve_returns(self):
        self.issue()
        services.claim_return(self.req_a1, self.staff_a1)
        url = reverse("inventory:approve_return", args=[self.req_a1.pk])
        for user in (self.staff_a1, self.sup_a, self.staff_b1):
            self.login(user)
            self.assertEqual(self.client.post(url, {"good": 1, "damaged": 0, "lost": 0}).status_code, 403)
        self.req_a1.refresh_from_db()
        self.assertEqual(self.req_a1.status, R.RETURN_CLAIMED)
        self.assertEqual(counts(self.item)["qty_issued"], 1)

    def test_split_good_damaged_lost(self):
        ItemRequest.objects.filter(pk=self.req_a1.pk).update(qty_requested=3)
        self.req_a1.refresh_from_db()
        self.issue(3)
        with self.assertRaisesMessage(TransitionError, "add up"):
            services.approve_return(self.req_a1, self.secretary, 1, 1, 0)
        with self.assertRaisesMessage(TransitionError, "write what happened"):
            services.approve_return(self.req_a1, self.secretary, 1, 1, 1)
        services.approve_return(self.req_a1, self.secretary, 1, 1, 1, "One cracked, one missing")
        c = counts(self.item)
        self.assertEqual((c["qty_available"], c["qty_damaged"], c["qty_lost"], c["qty_issued"]), (3, 1, 1, 0))
        self.assertEqual(self.req_a1.status, R.RETURNED)
        self.assertTrue(Notification.objects.filter(recipient=self.manager, kind="request.damaged_lost").exists())

    def test_all_lost_never_goes_to_available(self):
        self.issue()
        services.approve_return(self.req_a1, self.secretary, 0, 0, 1, "Lost on patrol")
        c = counts(self.item)
        self.assertEqual((c["qty_available"], c["qty_lost"]), (4, 1))
        self.assertEqual(self.req_a1.status, R.LOST)

    def test_not_received_puts_it_back_with_the_person(self):
        self.issue()
        services.claim_return(self.req_a1, self.staff_a1)
        services.not_received(self.req_a1, self.secretary, "Not in the store")
        self.assertEqual(self.req_a1.status, R.ISSUED)
        self.assertTrue(Notification.objects.filter(recipient=self.staff_a1, kind="request.not_received").exists())

    def test_keep_items_cannot_be_returned(self):
        req = services.create_request(self.keep_item, 1, "Boots worn out", self.staff_a1)
        services.approve_request(req, self.secretary, 1, hand_over_now=True)
        self.assertIsNone(req.expected_return_date)
        with self.assertRaises(TransitionError):
            services.claim_return(req, self.staff_a1)


class OverdueTests(OpsTestCase):
    def make_overdue(self, days_late):
        services.approve_request(self.req_a1, self.secretary, 1, self.later, hand_over_now=True)
        ItemRequest.objects.filter(pk=self.req_a1.pk).update(expected_return_date=self.today - timedelta(days=days_late))
        self.req_a1.refresh_from_db()

    def test_reminder_once_a_day(self):
        self.make_overdue(2)
        services.remind(self.req_a1, self.secretary)
        with self.assertRaisesMessage(TransitionError, "already"):
            services.remind(self.req_a1, self.secretary)

    def test_daily_checks_are_safe_to_run_twice(self):
        from core.checks import run_daily_checks

        self.make_overdue(9)
        first = run_daily_checks()
        self.assertEqual(first["item_reminders"], 1)
        self.assertIsNone(run_daily_checks())
        again = run_daily_checks(force=True)
        self.assertEqual(again["item_reminders"], 0)
        self.assertEqual(Notification.objects.filter(recipient=self.staff_a1, kind="request.reminder").count(), 1)
        self.assertTrue(Notification.objects.filter(recipient=self.manager, kind="request.very_late").exists())

    def test_overdue_page(self):
        self.make_overdue(1)
        self.login(self.secretary)
        self.assertContains(self.client.get(reverse("inventory:overdue")), "Torch")
