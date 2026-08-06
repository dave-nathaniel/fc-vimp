"""
VIMP — READ-ONLY audit: why duplicate documents appear in SAP ByD.

HYPOTHESIS UNDER TEST
  `vimp.tasks.create_inbound_delivery_notification_on_byd` (and its twin
  `create_invoice_on_byd`) retry the WHOLE function on failure, but the function
  is create-then-post. When `create_*` has already committed a document in ByD
  and the subsequent `post_*` fails with a lock error, `_schedule_byd_lock_retry`
  re-runs from the top -> a SECOND document is created. Because the ByD-facing ID
  carries two RANDOM letters (`f"{grn_number}{2 random uppercase}"`), ByD cannot
  reject the re-send as a duplicate.

  See vimp/tasks.py:290-395 (delivery notif) and :404-485 (invoice).

WHY THE DB "LOOKS FINE"
  Each attempt OVERWRITES grn.inbound_delivery_object_id / _notification_id, so
  the GRN row shows exactly ONE posting no matter how many documents ByD holds.
  The duplicates were never visible from the GRN table alone. The signal lives in
  ByDPostingStatus + the fact that an object_id exists at all.

THE HEADLINE DETECTOR (section 2)
  status == 'failed'  AND  inbound_delivery_object_id IS NOT NULL
    -> ByD DID return an ObjectID, i.e. a document was created and committed,
       yet the overall posting is recorded as failed. Every retry after that
       created another one. Expected ByD document count ~= retry_count + 1.

RUN (read-only; makes no writes and no ByD calls)
  python manage.py shell < diagnosis/audit_byd_duplicate_postings.py

  Optional:
    DAYS=90     limit to postings updated in the last N days (default: all time)
    VERBOSE=1   print the full error_message for each suspect row
"""
import os
from collections import Counter, defaultdict

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count

from byd_service.models import ByDPostingStatus
from byd_service.util import is_byd_lock_error
from egrn_service.models import GoodsReceivedNote
from invoice_service.models import Invoice

DAYS = int(os.getenv("DAYS", "0") or 0)
VERBOSE = os.getenv("VERBOSE") == "1"

NOTIF_TASK = "vimp.tasks.create_inbound_delivery_notification_on_byd"
INVOICE_TASK = "vimp.tasks.create_invoice_on_byd"
GRN_TASK = "vimp.tasks.create_grn_on_byd"
CANCEL_TASK = "vimp.tasks.cancel_inbound_delivery_notification_on_byd"


def banner(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def scoped(qs):
    if DAYS:
        from django.utils import timezone
        from datetime import timedelta
        return qs.filter(updated_at__gte=timezone.now() - timedelta(days=DAYS))
    return qs


banner(f"VIMP ByD DUPLICATE-POSTING AUDIT  |  scope: "
       f"{'last ' + str(DAYS) + ' days' if DAYS else 'all time'}")

grn_ct = ContentType.objects.get_for_model(GoodsReceivedNote)
invoice_ct = ContentType.objects.get_for_model(Invoice)

# ---------------------------------------------------------------------------
# 1. Retry pressure per task — how often does the retry path fire at all?
# ---------------------------------------------------------------------------
banner("[1] POSTING STATUS BREAKDOWN PER TASK")

all_status = scoped(ByDPostingStatus.objects.all())
print(f"   Total ByDPostingStatus rows in scope: {all_status.count()}\n")

for task in (NOTIF_TASK, INVOICE_TASK, GRN_TASK, CANCEL_TASK):
    rows = all_status.filter(django_q_task_name=task)
    total = rows.count()
    if not total:
        print(f"   {task.split('.')[-1]:<48} (no rows)")
        continue
    by_status = Counter(rows.values_list("status", flat=True))
    retried = rows.filter(retry_count__gt=0)
    # retry_count is the number of EXTRA full create+post attempts requested.
    extra_attempts = sum(retried.values_list("retry_count", flat=True))
    print(f"   {task.split('.')[-1]:<48} total={total}")
    print(f"        status: " + "  ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    print(f"        rows with retry_count>0: {retried.count()}"
          f"   sum(retry_count) = {extra_attempts}  <- extra full attempts requested")

# ---------------------------------------------------------------------------
# 2. HEADLINE: postings that failed AFTER ByD already committed a document.
#    These are the near-certain duplicates.
# ---------------------------------------------------------------------------
banner("[2] SUSPECTED DUPLICATES — failed AFTER a ByD document was created")

notif_rows = list(all_status.filter(django_q_task_name=NOTIF_TASK))
grn_ids = [r.object_id for r in notif_rows if r.content_type_id == grn_ct.id]
grns = {
    g.id: g for g in GoodsReceivedNote.objects.filter(id__in=grn_ids)
    .select_related("purchase_order")
}

suspects = []
lock_on_post = 0
for r in notif_rows:
    if r.content_type_id != grn_ct.id:
        continue
    grn = grns.get(r.object_id)
    if not grn:
        continue
    created_in_byd = bool(grn.inbound_delivery_object_id)
    if r.status == "failed" and created_in_byd:
        # A document exists in ByD, yet we recorded failure -> the failure was on
        # the POST step (or after), so every retry re-created the document.
        expected_docs = r.retry_count + 1
        is_lock = is_byd_lock_error(r.error_message or "")
        lock_on_post += 1 if is_lock else 0
        suspects.append((grn, r, expected_docs, is_lock))

suspects.sort(key=lambda x: -x[2])

if not suspects:
    print("   None found. Either the create step is what fails (no ObjectID stored),\n"
          "   or these rows were later overwritten by a successful attempt.\n"
          "   -> Go to section 3, which catches the 'succeeded on a later attempt' case.")
else:
    print(f"   {len(suspects)} GRN(s) recorded FAILED while holding a ByD ObjectID.")
    print(f"   {lock_on_post} of those carry a LOCK-shaped error message"
          f" (matches is_byd_lock_error).\n")
    print(f"   {'GRN':<12}{'PO':<10}{'retries':<9}{'~ByD docs':<11}{'lock?':<7}last notif ID")
    print("   " + "-" * 72)
    total_extra = 0
    for grn, r, expected_docs, is_lock in suspects:
        total_extra += expected_docs - 1
        po = getattr(grn.purchase_order, "po_id", "?")
        print(f"   {grn.grn_number:<12}{po:<10}{r.retry_count:<9}{expected_docs:<11}"
              f"{'YES' if is_lock else 'no':<7}{grn.inbound_delivery_notification_id}")
        if VERBOSE and r.error_message:
            print(f"        error: {r.error_message[:300]}")
    print("\n   " + "-" * 72)
    print(f"   ESTIMATED EXTRA (duplicate) ByD documents from this path: {total_extra}")

# ---------------------------------------------------------------------------
# 3. The quieter case: retried, then SUCCEEDED. The earlier attempts' documents
#    are still in ByD — and mark_success() erased the evidence of the failures.
# ---------------------------------------------------------------------------
banner("[3] SUCCEEDED-AFTER-RETRY — earlier attempts' documents remain in ByD")

succeeded_after_retry = [
    r for r in notif_rows
    if r.status == "success" and r.retry_count > 0 and r.content_type_id == grn_ct.id
]
if not succeeded_after_retry:
    print("   None. (Note: retry_count is not reset on success, so a zero here is"
          "\n   meaningful — it means no notification posting ever needed a retry.)")
else:
    print(f"   {len(succeeded_after_retry)} GRN(s) succeeded only after >=1 retry.")
    print("   Each earlier attempt that got past `create` left a document in ByD.\n")
    print(f"   {'GRN':<12}{'PO':<10}{'retries':<9}surviving notif ID")
    print("   " + "-" * 62)
    for r in sorted(succeeded_after_retry, key=lambda x: -x.retry_count):
        grn = grns.get(r.object_id)
        if not grn:
            continue
        po = getattr(grn.purchase_order, "po_id", "?")
        print(f"   {grn.grn_number:<12}{po:<10}{r.retry_count:<9}"
              f"{grn.inbound_delivery_notification_id}")
    print(f"\n   -> Check these GRN numbers in ByD. Look for InboundDelivery IDs that"
          f"\n      SHARE the grn_number prefix but differ in the two trailing letters."
          f"\n      That pattern is proof of the retry-from-create mechanism.")

# ---------------------------------------------------------------------------
# 4. Racing get_or_create — ByDPostingStatus has NO unique constraint on
#    (content_type, object_id, django_q_task_name). Two rows = two independent
#    retry chains for one GRN, each with its own retry_count.
# ---------------------------------------------------------------------------
banner("[4] DUPLICATE ByDPostingStatus ROWS (racing get_or_create)")

dupe_rows = (
    ByDPostingStatus.objects.values("content_type_id", "object_id", "django_q_task_name")
    .annotate(n=Count("id"))
    .filter(n__gt=1)
    .order_by("-n")
)
dupe_list = list(dupe_rows)
if not dupe_list:
    print("   None. get_or_create has not raced yet — but there is still no DB")
    print("   constraint preventing it (byd_service/migrations has no unique_together),")
    print("   so any idempotency guard built on this row can be bypassed under load.")
else:
    print(f"   {len(dupe_list)} (object, task) pair(s) have MORE THAN ONE status row.")
    print("   Each row runs its own retry chain -> retries fan out multiplicatively.\n")
    ct_names = {grn_ct.id: "GRN", invoice_ct.id: "Invoice"}
    for d in dupe_list[:40]:
        label = ct_names.get(d["content_type_id"], f"ct{d['content_type_id']}")
        ref = d["object_id"]
        if d["content_type_id"] == grn_ct.id:
            g = grns.get(ref) or GoodsReceivedNote.objects.filter(id=ref).first()
            ref = g.grn_number if g else ref
        siblings = ByDPostingStatus.objects.filter(
            content_type_id=d["content_type_id"],
            object_id=d["object_id"],
            django_q_task_name=d["django_q_task_name"],
        ).values_list("id", "status", "retry_count")
        print(f"   {label} {ref}  task={d['django_q_task_name'].split('.')[-1]}  rows={d['n']}")
        for sid, st, rc in siblings:
            print(f"        status_row id={sid}  status={st}  retry_count={rc}")

# ---------------------------------------------------------------------------
# 5. Same defect on the invoice path (live via invoice_service/models.py:165).
# ---------------------------------------------------------------------------
banner("[5] INVOICE PATH — identical create-then-post-then-retry shape")

inv_rows = list(all_status.filter(django_q_task_name=INVOICE_TASK))
inv_retried = [r for r in inv_rows if r.retry_count > 0]
if not inv_rows:
    print("   No invoice posting rows in scope.")
else:
    print(f"   {len(inv_rows)} invoice posting row(s); {len(inv_retried)} with retry_count>0.")
    if inv_retried:
        print("   create_invoice_on_byd has NO stored ObjectID field, so we cannot tell")
        print("   from the DB whether `create` had already committed. Treat every row")
        print("   below as a supplier invoice to verify manually in ByD.\n")
        print(f"   {'Invoice':<12}{'retries':<9}{'status':<10}lock-shaped error?")
        print("   " + "-" * 60)
        for r in sorted(inv_retried, key=lambda x: -x.retry_count):
            is_lock = is_byd_lock_error(r.error_message or "")
            print(f"   {r.object_id:<12}{r.retry_count:<9}{r.status:<10}"
                  f"{'YES' if is_lock else 'no'}")
            if VERBOSE and r.error_message:
                print(f"        error: {r.error_message[:300]}")

# ---------------------------------------------------------------------------
# 6. Pending scheduled retries — duplicates that have NOT happened yet.
# ---------------------------------------------------------------------------
banner("[6] PENDING LOCK-RETRY SCHEDULES (duplicates still queued)")

try:
    from django_q.models import Schedule
    pending = Schedule.objects.filter(name__contains="-lock-retry-")
    print(f"   {pending.count()} pending ONCE schedule(s) named '*-lock-retry-*'.")
    if pending.exists():
        print("   django-q deletes a ONCE schedule after it fires, so these are all")
        print("   still-to-run attempts. Each will create a NEW ByD document.\n")
        by_target = defaultdict(list)
        for s in pending.order_by("next_run")[:80]:
            by_target[s.func].append((s.name, s.args, s.next_run))
        for func, items in by_target.items():
            print(f"   {func}  ({len(items)})")
            for name, args, next_run in items:
                print(f"        {next_run}  args={args}  {name}")
except Exception as e:
    print(f"   Could not inspect django_q Schedule: {e}")

# ---------------------------------------------------------------------------
# 6b. Attempt sources from django-q's own Task table. Three distinct origins:
#       - attempt_count > 1 .......... broker RE-DELIVERY (worker killed by the
#         300s timeout mid-task -> never acked -> OrmQ re-presented every 360s.
#         django-q 1.3.9's ORM broker has NO max_attempts enforcement for kills:
#         save_task() only counts attempts that COMPLETE).
#       - name starts '[Retry ' ...... ADMIN manual retry (byd_service/admin.py
#         re-dispatches the whole create+post task for any failed posting).
#       - name contains '-lock-retry-' scheduled backoff chain (automatic).
#     Caveat: save_limit=1000 prunes old Success rows — counts are a floor.
# ---------------------------------------------------------------------------
banner("[6b] EXECUTION SOURCES per task func (django_q Task table)")

try:
    from django_q.models import Task

    for func in (NOTIF_TASK, INVOICE_TASK, GRN_TASK, CANCEL_TASK):
        rows = Task.objects.filter(func=func)
        total = rows.count()
        if not total:
            continue
        redelivered = rows.filter(attempt_count__gt=1)
        admin_retries = rows.filter(name__startswith="[Retry")
        lock_retries = rows.filter(name__contains="-lock-retry-")
        failed_execs = rows.filter(success=False).count()
        print(f"   {func.split('.')[-1]}")
        print(f"        executions recorded: {total}   (failed: {failed_execs})")
        print(f"        broker re-deliveries (attempt_count>1): {redelivered.count()}"
              f"   <- timeout-killed then re-run from create")
        for t in redelivered.order_by("-attempt_count")[:10]:
            print(f"             {t.name}  attempts={t.attempt_count}  success={t.success}")
        print(f"        admin manual retries ('[Retry ...'): {admin_retries.count()}")
        print(f"        scheduled lock-retries ('-lock-retry-'): {lock_retries.count()}")
except Exception as e:
    print(f"   Could not inspect django_q Task table: {e}")

# ---------------------------------------------------------------------------
# 7. Error-message shapes — which step actually fails?
# ---------------------------------------------------------------------------
banner("[7] FAILURE SIGNATURES (which step fails, and is it classified as a lock?)")

shapes = Counter()
for r in notif_rows + inv_rows:
    msg = (r.error_message or "").strip()
    if not msg:
        continue
    lock = "LOCK" if is_byd_lock_error(msg) else "not-lock"
    if "Object is locked" in msg:
        step = "pre-post check_object_lock() 423"
    elif "Error posting" in msg:
        step = "POST step"
    elif "Error creating" in msg:
        step = "CREATE step"
    elif "being posted by another worker" in msg:
        step = "po_write_lock not acquired (never touched ByD)"
    else:
        step = "other"
    shapes[(step, lock)] += 1

if not shapes:
    print("   No error messages recorded.")
else:
    print(f"   {'count':<8}{'classified':<12}step")
    print("   " + "-" * 66)
    for (step, lock), n in shapes.most_common():
        print(f"   {n:<8}{lock:<12}{step}")
    print("\n   KEY: any row that is 'LOCK' and NOT 'po_write_lock not acquired' was")
    print("   retried from the top by _schedule_byd_lock_retry. If its step is the")
    print("   POST step or the pre-post lock check, a document ALREADY existed in ByD")
    print("   and the retry duplicated it.")

banner("DONE — nothing was written; no ByD calls were made.")
