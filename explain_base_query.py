"""
Dump the full SQL and EXPLAIN for the base pending-approval queryset, and time
three query shapes to decide the fix approach.

RUN WITH CACHALOT OFF or the timings are served from cache and read as instant:
  docker compose exec -T -e CACHALOT_ENABLED=0 web python manage.py shell < explain_base_query.py

Read-only.
"""
import operator
import time
from functools import reduce
from django.conf import settings
from django.db import connection, reset_queries
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from approval_service.views import make_base_signable_queryset
from invoice_service.models import Invoice, WORKFLOW_RULES

settings.DEBUG = True


def timed(label, queryset):
    """Evaluate a queryset, print wall + db time. Repeat twice to expose caching."""
    for run in (1, 2):
        reset_queries()
        t = time.time()
        list(queryset)
        wall = (time.time() - t) * 1000
        db = sum(float(q['time']) for q in connection.queries) * 1000
        print(f"  {label} [run {run}]: {wall:7.0f} ms wall | {db:7.0f} ms db | {len(connection.queries)} q")

relevant_permissions = sorted({r for v in WORKFLOW_RULES.values() for r in v["roles"]})
content_type = ContentType.objects.get_for_model(Invoice)

# --- The full current query (what the view runs today) ---
full = make_base_signable_queryset(Invoice, content_type, relevant_permissions)\
    .filter(current_pending_signatory__in=relevant_permissions).order_by("date_created")[:15]

# --- MINIMAL: JSON filter + pending filter + order + limit. No annotations,
#     no .distinct(), no Exists. This is exactly the "cheap ID page" of approach (b). ---
q_objects = [Q(signatories__contains=perm) for perm in relevant_permissions]
json_query = reduce(operator.or_, q_objects)
minimal = Invoice.objects.filter(json_query).filter(
    current_pending_signatory__in=relevant_permissions
).order_by("date_created")[:15]

# --- NO-JSON: drop the (redundant for pending) signatories__contains filter,
#     keep only the indexable current_pending_signatory__in. ---
no_json = Invoice.objects.filter(
    current_pending_signatory__in=relevant_permissions
).order_by("date_created")[:15]

print("\n================ FULL SQL (current view query) ================\n")
print(str(full.query))


def explain(label, queryset):
    sql, params = queryset.query.sql_with_params()
    print(f"\n================ EXPLAIN: {label} ================\n")
    with connection.cursor() as cur:
        cur.execute("EXPLAIN " + sql, params)
        cols = [c[0] for c in cur.description]
        for row in cur.fetchall():
            print("  " + " | ".join(f"{c}={v}" for c, v in zip(cols, row)))


explain("FULL (annotations + distinct + Exists + JSON filter)", full)
explain("MINIMAL (JSON filter + pending, no annotations/distinct)", minimal)
explain("NO-JSON (pending filter only, indexable)", no_json)

print("\n================ TIMINGS (cachalot must be OFF) ================\n")
timed("FULL  (today's query)         ", full)
timed("MINIMAL (b: cheap ID page)    ", minimal)
timed("NO-JSON (drop redundant JSON) ", no_json)

print("\nDecision guide:")
print("  MINIMAL fast  -> approach (b): page IDs cheaply, then annotate only those 15.")
print("  MINIMAL slow but NO-JSON fast -> JSON filter is the cost; drop it (redundant")
print("                  for pending) and index current_pending_signatory.")
print("  Both slow     -> unindexed date_created filesort dominates; add an index.")
