"""
Verify the search-view fix:

  (1) SEMANTIC EQUIVALENCE (the discriminating gate): for a frozen candidate set,
      the NEW Python reduction must classify approved/declined IDENTICALLY to the
      OLD per-row correlated ORDER BY subquery. Asserted separately for approved
      AND declined (declined is where NULL-handling bugs hide).

  (2) TIMING: old correlated-subquery shape vs new light id__in shape, for the
      status=approved page the user reported (page=1 size=10).

Read-only. Run with cachalot OFF so timings are real:
  docker compose exec -T -e CACHALOT_ENABLED=0 web python manage.py shell < verify_search.py
"""
import operator
import time
from functools import reduce

from django.conf import settings
from django.db import connection, reset_queries
from django.db.models import Q, Subquery, OuterRef, BooleanField
from django.contrib.contenttypes.models import ContentType

from approval_service.models import Signature
from invoice_service.models import Invoice, WORKFLOW_RULES

settings.DEBUG = True

content_type = ContentType.objects.get_for_model(Invoice)
relevant_permissions = sorted({r for v in WORKFLOW_RULES.values() for r in v["roles"]})

# ---- Frozen candidate set: the JSON-filtered signatory scope, IDs frozen once. ----
q_objects = [Q(signatories__contains=perm) for perm in relevant_permissions]
json_query = reduce(operator.or_, q_objects)
frozen_ids = list(
    Invoice.objects.filter(json_query).order_by('id').values_list('id', flat=True)
)
frozen_set = set(frozen_ids)
print(f"Frozen candidate set: {len(frozen_ids)} invoices")

# ---- OLD classification: per-row correlated subquery, scoped to frozen set ----
old_qs = Invoice.objects.filter(id__in=frozen_ids).annotate(
    last_signature_accepted=Subquery(
        Signature.objects.filter(
            signable_type=content_type,
            signable_id=OuterRef('pk'),
        ).order_by('-date_signed').values('accepted')[:1],
        output_field=BooleanField(),
    )
)
old_approved = set(old_qs.filter(last_signature_accepted=True).values_list('id', flat=True))
old_declined = set(old_qs.filter(last_signature_accepted=False).values_list('id', flat=True))

# ---- NEW classification: single ordered scan, reduce latest-per-invoice in Python ----
latest_accepted = {}
for sid, accepted in (
    Signature.objects.filter(signable_type=content_type)
    .order_by('signable_id', '-date_signed')
    .values_list('signable_id', 'accepted')
):
    latest_accepted.setdefault(sid, accepted)
new_approved = {sid for sid, acc in latest_accepted.items() if acc is True} & frozen_set
new_declined = {sid for sid, acc in latest_accepted.items() if acc is False} & frozen_set

print("\n================ SEMANTIC EQUIVALENCE GATE ================")
print(f"  approved: old={len(old_approved):5d}  new={len(new_approved):5d}  "
      f"{'MATCH' if old_approved == new_approved else 'MISMATCH'}")
if old_approved != new_approved:
    print(f"    only-old: {sorted(old_approved - new_approved)[:20]}")
    print(f"    only-new: {sorted(new_approved - old_approved)[:20]}")
print(f"  declined: old={len(old_declined):5d}  new={len(new_declined):5d}  "
      f"{'MATCH' if old_declined == new_declined else 'MISMATCH'}")
if old_declined != new_declined:
    print(f"    only-old: {sorted(old_declined - new_declined)[:20]}")
    print(f"    only-new: {sorted(new_declined - old_declined)[:20]}")

assert old_approved == new_approved, "approved classification diverged"
assert old_declined == new_declined, "declined classification diverged"
print("  -> BOTH MATCH. Semantics preserved.")

# ---- TIMING: the reported request, status=approved page=1 size=10 ----
def timed(label, fn):
    for run in (1, 2):
        reset_queries()
        t = time.time()
        n = fn()
        wall = (time.time() - t) * 1000
        db = sum(float(q['time']) for q in connection.queries) * 1000
        print(f"  {label} [run {run}]: {wall:8.0f} ms wall | {db:8.0f} ms db | "
              f"{len(connection.queries):4d} q | {n} rows")

print("\n================ TIMING: status=approved page=1 size=10 ================")

def old_page():
    qs = Invoice.objects.filter(json_query).annotate(
        last_signature_accepted=Subquery(
            Signature.objects.filter(
                signable_type=content_type, signable_id=OuterRef('pk')
            ).order_by('-date_signed').values('accepted')[:1],
            output_field=BooleanField(),
        )
    ).filter(last_signature_accepted=True).order_by('-date_created', '-id')
    return len(list(qs[0:10].values_list('id', flat=True)))

def new_page():
    latest = {}
    for sid, accepted in (
        Signature.objects.filter(signable_type=content_type)
        .order_by('signable_id', '-date_signed').values_list('signable_id', 'accepted')
    ):
        latest.setdefault(sid, accepted)
    ids = [sid for sid, acc in latest.items() if acc is True]
    qs = Invoice.objects.filter(json_query).filter(id__in=ids).order_by('-date_created', '-id')
    return len(list(qs[0:10].values_list('id', flat=True)))

timed("OLD (correlated subquery)", old_page)
timed("NEW (scan + id__in)      ", new_page)

# ---- REGRESSION GUARD: the q free-text path applies .distinct(). Listing full rows
#      (SELECT DISTINCT * ... ORDER BY date_created) must NOT raise MySQL 3065. Listing
#      .values_list('id') on the same query WOULD. Prove the shipped shape is safe. ----
print("\n================ DISTINCT + ORDER BY (q path) regression guard ================")
distinct_qs = (
    Invoice.objects.filter(json_query)
    .filter(Q(description__icontains='a'))   # any q-shaped filter to mirror the join
    .order_by('-date_created', '-id')
    .distinct()
)
try:
    rows = list(distinct_qs[0:10])           # SELECT DISTINCT * ... ORDER BY  -> safe
    print(f"  list(distinct_qs[:10])           -> OK, {len(rows)} rows (shipped shape)")
except Exception as e:
    print(f"  list(distinct_qs[:10])           -> RAISED: {e}")
try:
    bad = list(distinct_qs[0:10].values_list('id', flat=True))  # the trap
    print(f"  .values_list('id') on distinct   -> OK on this MySQL config ({len(bad)} rows)")
except Exception as e:
    print(f"  .values_list('id') on distinct   -> RAISED (expected under strict mode): {e}")
