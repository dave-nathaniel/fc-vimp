"""
VIMP pending-approval slowness diagnostic.

RUN IT TWICE so the comparison is meaningful:

  # (a) cachalot OFF — shows the TRUE query count (N+1 exposed, cache cannot hide it)
  CACHALOT_ENABLED=0 python manage.py shell < diagnose_pending.py

  # (b) cachalot ON (normal) — shows DB queries when the cache is masking the N+1
  python manage.py shell < diagnose_pending.py

WHY TWICE: section [2] counts connection.queries, which is DB-only. With cachalot
warm, the per-row aggregate queries are served from Redis and never reach MySQL,
so they do NOT appear in the count. Run (a) to see the real shape; the gap between
(a) and (b) is exactly the work cachalot is absorbing (and stops absorbing when
its cache goes cold). The Redis section [3] is valid in either run.

Read-only. Touches no data. Prints a report covering:
  1. Data volumes (the "did we cross a threshold" question)
  2. Live query count to render one pending page (the N+1 question)
  3. Redis health: memory, evictions, keyspace, cachalot footprint (the "this week" question)
"""
import time
from django.db import connection, reset_queries
from django.conf import settings
from django.contrib.contenttypes.models import ContentType

print("\n" + "=" * 70)
print("VIMP PENDING-APPROVAL DIAGNOSTIC")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. DATA VOLUMES
# ---------------------------------------------------------------------------
print("\n[1] DATA VOLUMES")
try:
    from invoice_service.models import Invoice, InvoiceLineItem
    from approval_service.models import Signature
    from egrn_service.models import (
        PurchaseOrder, PurchaseOrderLineItem,
        GoodsReceivedNote, GoodsReceivedLineItem,
    )

    print(f"  Invoices total .................. {Invoice.objects.count():,}")
    print(f"  Invoices pending (cps not null) . "
          f"{Invoice.objects.filter(current_pending_signatory__isnull=False).count():,}")
    print(f"  InvoiceLineItems ................ {InvoiceLineItem.objects.count():,}")
    print(f"  Signatures ...................... {Signature.objects.count():,}")
    print(f"  PurchaseOrders .................. {PurchaseOrder.objects.count():,}")
    print(f"  PurchaseOrderLineItems .......... {PurchaseOrderLineItem.objects.count():,}")
    print(f"  GoodsReceivedNotes .............. {GoodsReceivedNote.objects.count():,}")
    print(f"  GoodsReceivedLineItems .......... {GoodsReceivedLineItem.objects.count():,}")

    # failed_line_items blob size — the new field from commit 040a6dd
    pos_with_failures = PurchaseOrder.objects.exclude(failed_line_items=[]).count()
    print(f"  POs with failed_line_items ...... {pos_with_failures:,}")
    if pos_with_failures:
        import json
        sizes = [
            len(json.dumps(po.failed_line_items))
            for po in PurchaseOrder.objects.exclude(failed_line_items=[])[:200]
        ]
        print(f"    avg blob bytes (first 200) .... {sum(sizes)//max(len(sizes),1):,}")
        print(f"    max blob bytes ................ {max(sizes):,}")
except Exception as e:
    print(f"  ERROR collecting volumes: {e}")

# ---------------------------------------------------------------------------
# 2. LIVE QUERY COUNT FOR ONE PENDING PAGE
# ---------------------------------------------------------------------------
print("\n[2] QUERY COUNT — rendering one 'pending' page (size=15)")
_cachalot_on = getattr(settings, "CACHALOT_ENABLED", False)
print(f"    cachalot ENABLED = {_cachalot_on}  "
      f"({'queries hidden by cache — re-run with CACHALOT_ENABLED=0' if _cachalot_on else 'TRUE query count exposed'})")
print("    (DEBUG must capture queries; we force it on for this block)")
_old_debug = settings.DEBUG
settings.DEBUG = True
try:
    from approval_service.views import (
        make_filtered_signable_queryset, hydrate_signables_by_ids, build_product_config_map,
    )
    from approval_service.utils import ApprovalUtilities
    from invoice_service.models import Invoice, WORKFLOW_RULES
    from invoice_service.serializers import InvoiceSerializer
    from collections import defaultdict

    # Use the union of all signatory roles so the queryset isn't empty,
    # regardless of which user we are. This mirrors a privileged approver.
    relevant_permissions = sorted({r for v in WORKFLOW_RULES.values() for r in v["roles"]})
    content_type = ContentType.objects.get_for_model(Invoice)

    # --- COUNT EQUIVALENCE: the fix changed which queryset .count() runs on
    #     (heavy aggregate+distinct -> light filter-only). Prove they're equal. ---
    from approval_service.views import make_base_signable_queryset
    from django.db.models import Exists as _Exists, OuterRef as _OuterRef
    heavy_pending = make_base_signable_queryset(
        Invoice, content_type, relevant_permissions
    ).filter(current_pending_signatory__in=relevant_permissions).count()
    light_pending = make_filtered_signable_queryset(
        Invoice, relevant_permissions
    ).filter(current_pending_signatory__in=relevant_permissions).count()
    # completed branch: old user_has_signed=True annotation vs new Exists filter
    heavy_completed = make_base_signable_queryset(
        Invoice, content_type, relevant_permissions
    ).filter(user_has_signed=True).count()
    light_completed = make_filtered_signable_queryset(
        Invoice, relevant_permissions
    ).filter(_Exists(Signature.objects.filter(
        signable_type=content_type, signable_id=_OuterRef('pk'),
        metadata__acting_as__in=relevant_permissions))).count()
    print("  COUNT EQUIVALENCE (must match):")
    print(f"    pending   heavy={heavy_pending}  light={light_pending}  "
          f"{'OK' if heavy_pending == light_pending else '*** MISMATCH ***'}")
    print(f"    completed heavy={heavy_completed}  light={light_completed}  "
          f"{'OK' if heavy_completed == light_completed else '*** MISMATCH ***'}")
    print("")

    # --- TOTALS EQUIVALENCE: the hydrate path now computes gross/tax/net via a
    #     separate aggregate instead of the old SUM() annotation. Prove per-id equal. ---
    _probe_ids = list(
        make_filtered_signable_queryset(Invoice, relevant_permissions)
        .filter(current_pending_signatory__in=relevant_permissions)
        .order_by("date_created").values_list("id", flat=True)[:15]
    )
    old_totals = {
        o.id: (o.gross_total_annotated, o.total_tax_amount_annotated, o.net_total_annotated)
        for o in make_base_signable_queryset(Invoice, content_type, relevant_permissions)
                    .filter(id__in=_probe_ids)
    }
    new_objs = hydrate_signables_by_ids(Invoice, content_type, relevant_permissions, _probe_ids, "date_created")
    new_totals = {
        o.id: (o.gross_total_annotated, o.total_tax_amount_annotated, o.net_total_annotated)
        for o in new_objs
    }
    mismatches = [i for i in _probe_ids if old_totals.get(i) != new_totals.get(i)]
    print("  TOTALS EQUIVALENCE (old annotation vs new hydrate, per id):")
    print(f"    {len(_probe_ids)} invoices checked  "
          f"{'OK — all match' if not mismatches else f'*** {len(mismatches)} MISMATCH: {mismatches[:5]} ***'}")
    if mismatches:
        for i in mismatches[:3]:
            print(f"      id={i}  old={old_totals.get(i)}  new={new_totals.get(i)}")
    print("")

    def db_time_ms():
        # Sum of all captured query execution times (DEBUG must be on).
        return sum(float(q['time']) for q in connection.queries) * 1000

    # --- PHASE A: mirror the view's two-phase flow — light filter+paginate,
    #     then hydrate only the page (annotations/Exists/prefetch on <=15 rows) ---
    reset_queries()
    tA = time.time()
    light = make_filtered_signable_queryset(Invoice, relevant_permissions)
    light = light.filter(current_pending_signatory__in=relevant_permissions)
    light = light.order_by("date_created")
    page_ids = list(light.values_list("id", flat=True)[:15])   # cheap LIMIT 15
    page = hydrate_signables_by_ids(Invoice, content_type, relevant_permissions, page_ids, "date_created")
    phaseA_wall = (time.time() - tA) * 1000
    phaseA_db = db_time_ms()
    phaseA_q = len(connection.queries)

    # --- PHASE B: signature prefetch + product config map (view setup) ---
    reset_queries()
    tB = time.time()
    ids = [obj.id for obj in page]
    sigs_by_id = defaultdict(list)
    if ids:
        for sig in Signature.objects.select_related("signer", "predecessor").filter(
            signable_type=content_type, signable_id__in=ids
        ).order_by("-date_signed"):
            sigs_by_id[sig.signable_id].append(sig)
    product_config_map = build_product_config_map(page)
    phaseB_wall = (time.time() - tB) * 1000
    phaseB_db = db_time_ms()
    phaseB_q = len(connection.queries)

    # --- PHASE C: serialization only ---
    reset_queries()
    tC = time.time()
    data = InvoiceSerializer(
        page, many=True,
        context={
            "signatures_by_id": dict(sigs_by_id),
            "product_config_map": product_config_map,
        },
    ).data
    phaseC_wall = (time.time() - tC) * 1000
    phaseC_db = db_time_ms()
    phaseC_q = len(connection.queries)

    total_wall = phaseA_wall + phaseB_wall + phaseC_wall
    total_db = phaseA_db + phaseB_db + phaseC_db
    total_q = phaseA_q + phaseB_q + phaseC_q

    print(f"  Rows serialized ................. {len(data)}")
    print(f"  TOTAL QUERIES ................... {total_q}")
    print(f"  TOTAL WALL ...................... {total_wall:.0f} ms")
    print(f"  TOTAL DB TIME (sum of queries) .. {total_db:.0f} ms")
    print(f"  PYTHON/NON-DB TIME .............. {total_wall - total_db:.0f} ms  "
          f"({'DB-BOUND' if total_db > 0.6*total_wall else 'PYTHON/CPU-BOUND' if total_db < 0.4*total_wall else 'MIXED'})")
    print("")
    print(f"  Phase A (queryset eval + __init__):  {phaseA_wall:7.0f} ms wall | {phaseA_db:7.0f} ms db | {phaseA_q:4d} q")
    print(f"  Phase B (signature/config setup):    {phaseB_wall:7.0f} ms wall | {phaseB_db:7.0f} ms db | {phaseB_q:4d} q")
    print(f"  Phase C (serialization):             {phaseC_wall:7.0f} ms wall | {phaseC_db:7.0f} ms db | {phaseC_q:4d} q")

    # Re-evaluate everything once more under a single capture so we can rank
    # individual queries by DURATION (the metric that actually matters).
    reset_queries()
    light2 = make_filtered_signable_queryset(Invoice, relevant_permissions)\
        .filter(current_pending_signatory__in=relevant_permissions).order_by("date_created")
    page2_ids = list(light2.values_list("id", flat=True)[:15])
    page2 = hydrate_signables_by_ids(Invoice, content_type, relevant_permissions, page2_ids, "date_created")
    ids2 = [o.id for o in page2]
    if ids2:
        list(Signature.objects.select_related("signer", "predecessor").filter(
            signable_type=content_type, signable_id__in=ids2).order_by("-date_signed"))
    _ = InvoiceSerializer(page2, many=True, context={
        "signatures_by_id": {}, "product_config_map": build_product_config_map(page2)}).data

    ranked = sorted(connection.queries, key=lambda q: float(q['time']), reverse=True)
    print("\n  SLOWEST queries by execution time (the real cost):")
    for q in ranked[:6]:
        print(f"    {float(q['time'])*1000:7.1f} ms  {q['sql'][:95]}")

    # Also show the time grouped by query shape (count x cumulative time).
    from collections import defaultdict as _dd
    shape_time = _dd(lambda: [0, 0.0])
    for q in connection.queries:
        k = q['sql'][:70]
        shape_time[k][0] += 1
        shape_time[k][1] += float(q['time']) * 1000
    print("\n  Cumulative time by query shape (count x total ms):")
    for k, (c, t) in sorted(shape_time.items(), key=lambda kv: kv[1][1], reverse=True)[:8]:
        print(f"    x{c:>4}  {t:8.1f} ms total  {k}")
except Exception as e:
    import traceback
    print(f"  ERROR measuring queries: {e}")
    traceback.print_exc()
finally:
    settings.DEBUG = _old_debug
    reset_queries()

# ---------------------------------------------------------------------------
# 2B. SUMMARY VIEW (/approvals/v1/summary/invoice) — the ACTUAL slow endpoint.
#     Decompose into (a) the unbounded Count x5 aggregate and (b) the top-10
#     serialization, and verify a proposed cheap-counter rewrite is equivalent.
# ---------------------------------------------------------------------------
print("\n[2B] SUMMARY VIEW decomposition (the endpoint the screen actually calls)")
_old_debug2 = settings.DEBUG
settings.DEBUG = True
try:
    from django.db.models import Count, Q, Subquery, BooleanField, Exists, OuterRef
    from approval_service.views import make_base_signable_queryset, make_filtered_signable_queryset, \
        hydrate_signables_by_ids, build_product_config_map
    from invoice_service.models import Invoice, WORKFLOW_RULES
    from invoice_service.serializers import InvoiceSerializer

    relevant_permissions = sorted({r for v in WORKFLOW_RULES.values() for r in v["roles"]})
    content_type = ContentType.objects.get_for_model(Invoice)

    def db_ms():
        return sum(float(q['time']) for q in connection.queries) * 1000

    # --- (a) CURRENT aggregate: heavy queryset + last_signature_accepted subquery,
    #     unbounded, wrapped in Count x5. This is the suspected ~60s operation. ---
    reset_queries()
    ta = time.time()
    heavy = make_base_signable_queryset(Invoice, content_type, relevant_permissions)
    latest_sig_sub = Signature.objects.filter(
        signable_type=content_type, signable_id=OuterRef('pk'),
        metadata__acting_as__in=relevant_permissions,
    ).order_by('-date_signed').values('accepted')[:1]
    heavy = heavy.annotate(last_signature_accepted=Subquery(latest_sig_sub, output_field=BooleanField()))
    old_counters = heavy.aggregate(
        total_count=Count('id'),
        pending_count=Count('id', filter=Q(current_pending_signatory__in=relevant_permissions)),
        completed_count=Count('id', filter=Q(user_has_signed=True)),
        rejected_count=Count('id', filter=Q(last_signature_accepted=False)),
        accepted_count=Count('id', filter=Q(last_signature_accepted=True)),
    )
    agg_wall = (time.time() - ta) * 1000
    agg_db = db_ms()
    print(f"  (a) CURRENT aggregate(Count x5):  {agg_wall:8.0f} ms wall | {agg_db:8.0f} ms db | {len(connection.queries)} q")
    print(f"      counters = {old_counters}")

    # --- (b) CURRENT top-10 pending serialization (heavy queryset, no LIMIT push) ---
    reset_queries()
    tb = time.time()
    recent = list(heavy.filter(current_pending_signatory__in=relevant_permissions).order_by('-date_created')[:10])
    _ = InvoiceSerializer(recent, many=True).data
    top10_wall = (time.time() - tb) * 1000
    top10_db = db_ms()
    print(f"  (b) CURRENT top-10 serialize:     {top10_wall:8.0f} ms wall | {top10_db:8.0f} ms db | {len(connection.queries)} q")

    print(f"\n  SUMMARY VIEW server-side total (a+b): {agg_wall + top10_wall:.0f} ms")
    print("  (Browser showed ~1.1 min; if this is far less, the rest is auth/preflight.)")

    # --- PROPOSED cheap rewrite: counters as independent light counts ---
    reset_queries()
    tc = time.time()
    light = make_filtered_signable_queryset(Invoice, relevant_permissions)
    new_total = light.count()
    new_pending = light.filter(current_pending_signatory__in=relevant_permissions).count()
    sig_exists = Exists(Signature.objects.filter(
        signable_type=content_type, signable_id=OuterRef('pk'),
        metadata__acting_as__in=relevant_permissions))
    new_completed = light.filter(sig_exists).count()
    # rejected/accepted: latest signature among the user's roles was rejected/accepted
    light_acc = light.annotate(last_signature_accepted=Subquery(latest_sig_sub, output_field=BooleanField()))
    new_rejected = light_acc.filter(last_signature_accepted=False).count()
    new_accepted = light_acc.filter(last_signature_accepted=True).count()
    new_wall = (time.time() - tc) * 1000
    new_db = db_ms()
    new_counters = {
        'total_count': new_total, 'pending_count': new_pending, 'completed_count': new_completed,
        'rejected_count': new_rejected, 'accepted_count': new_accepted,
    }
    print(f"\n  PROPOSED cheap counters:          {new_wall:8.0f} ms wall | {new_db:8.0f} ms db | {len(connection.queries)} q")
    print(f"      counters = {new_counters}")
    match = all(old_counters[k] == new_counters[k] for k in old_counters)
    print("\n  COUNTER EQUIVALENCE (old aggregate vs proposed):")
    for k in old_counters:
        ok = old_counters[k] == new_counters[k]
        print(f"    {k:16} old={old_counters[k]:>6}  new={new_counters[k]:>6}  {'OK' if ok else '*** MISMATCH ***'}")
    print(f"  => {'ALL MATCH — rewrite is safe' if match else 'MISMATCH — do NOT ship rewrite as-is'}")
except Exception as e:
    import traceback
    print(f"  ERROR in summary decomposition: {e}")
    traceback.print_exc()
finally:
    settings.DEBUG = _old_debug2
    reset_queries()

# ---------------------------------------------------------------------------
# 3. REDIS HEALTH + CACHALOT FOOTPRINT
# ---------------------------------------------------------------------------
print("\n[3] REDIS HEALTH")
try:
    from django_redis import get_redis_connection
    r = get_redis_connection("default")

    info_mem = r.info("memory")
    info_stats = r.info("stats")
    used = info_mem.get("used_memory_human")
    maxmem = info_mem.get("maxmemory_human")
    policy = info_mem.get("maxmemory_policy")
    evicted = info_stats.get("evicted_keys")
    hits = info_stats.get("keyspace_hits", 0)
    misses = info_stats.get("keyspace_misses", 0)
    dbsize = r.dbsize()

    print(f"  used_memory ..................... {used}")
    print(f"  maxmemory ....................... {maxmem}  (0 = unlimited)")
    print(f"  maxmemory_policy ................ {policy}")
    print(f"  evicted_keys .................... {evicted:,}")
    total_lookups = hits + misses
    hit_rate = (hits / total_lookups * 100) if total_lookups else 0
    print(f"  keyspace_hits ................... {hits:,}")
    print(f"  keyspace_misses ................. {misses:,}")
    print(f"  hit_rate ........................ {hit_rate:.1f}%")
    print(f"  DBSIZE (total keys) ............. {dbsize:,}")

    if evicted and int(evicted) > 0:
        print("  >>> EVICTIONS PRESENT: Redis is full and dropping keys.")
        print("      This makes the 'cache' cold — every approval read recomputes.")

    # Cachalot vs manual-cache key breakdown (SCAN, non-blocking-ish, capped)
    prefix = settings.CACHES["default"].get("KEY_PREFIX", "")
    patterns = {
        "cachalot": f"*cachalot*",
        "signables (manual)": f"*signables*",
        "count (manual)": f"*count*",
        "sessions": f"*session*",
    }
    print("\n  Key population by category (SCAN sample, capped 50k each):")
    for label, pat in patterns.items():
        full = f"{prefix}:{pat}" if prefix else pat
        count = 0
        for _ in r.scan_iter(match=full, count=1000):
            count += 1
            if count >= 50000:
                break
        suffix = "+" if count >= 50000 else ""
        print(f"    {label:<22} {count:,}{suffix}")
except Exception as e:
    import traceback
    print(f"  ERROR reading Redis: {e}")
    traceback.print_exc()

print("\n" + "=" * 70)
print("END OF DIAGNOSTIC")
print("=" * 70 + "\n")
