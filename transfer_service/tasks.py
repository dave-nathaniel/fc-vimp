"""
Tasks moved to vimp/tasks.py.

This module is intentionally empty. The original file had a module-level ImportError
(GoodsIssueNote and SalesOrder don't exist in transfer_service/models.py) which
prevented Django Q workers from loading any tasks defined here.

Active task: sync_approved_receipt_to_sap → vimp.tasks.sync_approved_receipt_to_sap
"""
