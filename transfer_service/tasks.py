"""
Async tasks for transfer service external integrations
"""
import logging
import time
from django_q.tasks import async_task
from django.utils import timezone
from .models import GoodsIssueNote, TransferReceiptNote, SalesOrder

logger = logging.getLogger(__name__)


class SAPIntegrationError(Exception):
    """Custom exception for SAP integration errors"""
    pass


class RetryableError(Exception):
    """Exception for errors that should be retried"""
    pass


def retry_on_failure(max_retries=3, delay=5):
    """
    Decorator to retry function on failure with exponential backoff
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except RetryableError as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {max_retries} attempts failed for {func.__name__}")
                except Exception as e:
                    # Non-retryable errors
                    logger.error(f"Non-retryable error in {func.__name__}: {e}")
                    raise
            
            # If we get here, all retries failed
            raise last_exception
        return wrapper
    return decorator


def post_goods_issue_to_icg(goods_issue_id: int):
    """
    Async task to post goods issue to ICG inventory system
    This will be implemented when ICG integration is added
    """
    try:
        goods_issue = GoodsIssueNote.objects.get(id=goods_issue_id)
        logger.info(f"Processing ICG posting for goods issue {goods_issue.issue_number}")
        
        # Placeholder for ICG integration
        # This will be implemented in task 3.3
        logger.warning("ICG integration not yet implemented")
        
    except GoodsIssueNote.DoesNotExist:
        logger.error(f"Goods issue with ID {goods_issue_id} not found")
    except Exception as e:
        logger.error(f"Error posting goods issue {goods_issue_id} to ICG: {e}")


@retry_on_failure(max_retries=3, delay=5)
def post_goods_issue_to_sap(goods_issue_id: int):
    """
    Async task to post goods issue to SAP ByD with retry logic
    """
    from byd_service.rest import RESTServices
    
    try:
        goods_issue = GoodsIssueNote.objects.get(id=goods_issue_id)
        logger.info(f"Processing SAP posting for goods issue {goods_issue.issue_number}")
        
        # Skip if already posted to SAP
        if goods_issue.posted_to_sap:
            logger.info(f"Goods issue {goods_issue.issue_number} already posted to SAP")
            return
        
        # Validate goods issue has line items
        if not goods_issue.line_items.exists():
            raise SAPIntegrationError(f"Goods issue {goods_issue.issue_number} has no line items")
        
        # Validate source store has required SAP identifiers
        if not (goods_issue.source_store.byd_cost_center_code or goods_issue.source_store.icg_warehouse_code):
            raise SAPIntegrationError(f"Source store {goods_issue.source_store.store_name} missing SAP identifiers")
        
        # Initialize SAP ByD REST service
        try:
            byd_service = RESTServices()
        except Exception as e:
            logger.error(f"Failed to initialize SAP ByD service: {e}")
            raise RetryableError(f"SAP ByD service initialization failed: {e}")
        
        # Prepare goods issue data for SAP ByD
        goods_issue_data = {
            "TypeCode": "01",  # Goods Issue type code
            "PostingDate": goods_issue.created_date.strftime("%Y-%m-%d"),
            "DocumentDate": goods_issue.created_date.strftime("%Y-%m-%d"),
            "Note": f"Store-to-store transfer goods issue - GI-{goods_issue.issue_number}",
            "Item": []
        }
        
        # Add line items with validation
        for line_item in goods_issue.line_items.all():
            if not line_item.product_id:
                raise SAPIntegrationError(f"Line item missing product ID: {line_item}")
            
            if line_item.quantity_issued <= 0:
                raise SAPIntegrationError(f"Invalid quantity for line item: {line_item}")
            
            item_data = {
                "ProductID": line_item.product_id,
                "Quantity": str(line_item.quantity_issued),
                "QuantityUnitCode": line_item.sales_order_line_item.unit_of_measurement or "EA",
                "SourceLogisticsAreaID": goods_issue.source_store.byd_cost_center_code or goods_issue.source_store.icg_warehouse_code,
                "SalesOrderID": str(goods_issue.sales_order.sales_order_id),
                "SalesOrderItemID": line_item.sales_order_line_item.object_id,
                "Note": f"Transfer to {goods_issue.sales_order.destination_store.store_name}"
            }
            goods_issue_data["Item"].append(item_data)
        
        # Create goods issue in SAP ByD
        logger.info(f"Creating goods issue in SAP ByD for GI-{goods_issue.issue_number}")
        try:
            response = byd_service.create_goods_issue(goods_issue_data)
        except Exception as e:
            logger.error(f"SAP ByD create_goods_issue failed: {e}")
            if "authentication" in str(e).lower() or "unauthorized" in str(e).lower():
                raise RetryableError(f"SAP ByD authentication error: {e}")
            elif "timeout" in str(e).lower() or "connection" in str(e).lower():
                raise RetryableError(f"SAP ByD connection error: {e}")
            else:
                raise SAPIntegrationError(f"SAP ByD create goods issue failed: {e}")
        
        # Validate response structure
        if not response or not isinstance(response, dict):
            raise RetryableError("Invalid response from SAP ByD create_goods_issue")
        
        results = response.get("d", {}).get("results")
        if not results or not results.get("ObjectID"):
            logger.error(f"Invalid SAP ByD response structure: {response}")
            raise RetryableError("Invalid response structure from SAP ByD")
        
        object_id = results["ObjectID"]
        logger.info(f"Goods issue created in SAP ByD with ObjectID: {object_id}")
        
        # Post the goods issue
        logger.info(f"Posting goods issue {object_id} in SAP ByD")
        try:
            post_response = byd_service.post_goods_issue(object_id)
        except Exception as e:
            logger.error(f"SAP ByD post_goods_issue failed: {e}")
            if "locked" in str(e).lower():
                raise RetryableError(f"SAP ByD object locked: {e}")
            elif "authentication" in str(e).lower() or "unauthorized" in str(e).lower():
                raise RetryableError(f"SAP ByD authentication error: {e}")
            elif "timeout" in str(e).lower() or "connection" in str(e).lower():
                raise RetryableError(f"SAP ByD connection error: {e}")
            else:
                raise SAPIntegrationError(f"SAP ByD post goods issue failed: {e}")
        
        # Validate post response
        if not post_response:
            raise RetryableError("Empty response from SAP ByD post_goods_issue")
        
        # Update goods issue as posted to SAP
        goods_issue.posted_to_sap = True
        goods_issue.metadata.update({
            'sap_object_id': object_id,
            'sap_posted_date': timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            'sap_create_response': results,
            'sap_post_response': post_response
        })
        goods_issue.save()
        
        logger.info(f"Goods issue {goods_issue.issue_number} successfully posted to SAP ByD")
        
    except GoodsIssueNote.DoesNotExist:
        logger.error(f"Goods issue with ID {goods_issue_id} not found")
        raise SAPIntegrationError(f"Goods issue with ID {goods_issue_id} not found")
    except (SAPIntegrationError, RetryableError):
        # Re-raise these specific exceptions for proper handling
        raise
    except Exception as e:
        logger.error(f"Unexpected error posting goods issue {goods_issue_id} to SAP: {e}")
        raise SAPIntegrationError(f"Unexpected error: {e}")


def update_transfer_receipt_inventory(receipt_id: int):
    """
    Async task to update ICG inventory for transfer receipt
    This will be implemented when ICG integration is added
    """
    try:
        receipt = TransferReceiptNote.objects.get(id=receipt_id)
        logger.info(f"Processing ICG inventory update for receipt {receipt.receipt_number}")
        
        # Placeholder for ICG integration
        # This will be implemented in task 4.3
        logger.warning("ICG integration not yet implemented")
        
    except TransferReceiptNote.DoesNotExist:
        logger.error(f"Transfer receipt with ID {receipt_id} not found")
    except Exception as e:
        logger.error(f"Error updating inventory for receipt {receipt_id}: {e}")


@retry_on_failure(max_retries=3, delay=5)
def update_sales_order_status(sales_order_id: int):
    """
    Async task to update sales order status in SAP ByD with retry logic
    """
    from byd_service.rest import RESTServices
    
    try:
        sales_order = SalesOrder.objects.get(id=sales_order_id)
        logger.info(f"Processing SAP status update for sales order {sales_order.sales_order_id}")
        
        # Initialize SAP ByD REST service
        try:
            byd_service = RESTServices()
        except Exception as e:
            logger.error(f"Failed to initialize SAP ByD service: {e}")
            raise RetryableError(f"SAP ByD service initialization failed: {e}")
        
        # Calculate current delivery status based on line items
        delivery_status = sales_order.delivery_status
        status_code = delivery_status[0]  # Get the status code from tuple
        
        # Skip update if status hasn't changed
        if sales_order.delivery_status_code == status_code:
            logger.info(f"Sales order {sales_order.sales_order_id} status unchanged ({status_code})")
            return
        
        logger.info(f"Updating sales order {sales_order.sales_order_id} status to {status_code} ({delivery_status[1]})")
        
        # Validate sales order has required data
        if not sales_order.object_id:
            raise SAPIntegrationError(f"Sales order {sales_order.sales_order_id} missing ObjectID")
        
        # Update sales order status in SAP ByD
        try:
            success = byd_service.update_sales_order_status(
                str(sales_order.sales_order_id), 
                status_code
            )
        except Exception as e:
            logger.error(f"SAP ByD update_sales_order_status failed: {e}")
            if "authentication" in str(e).lower() or "unauthorized" in str(e).lower():
                raise RetryableError(f"SAP ByD authentication error: {e}")
            elif "timeout" in str(e).lower() or "connection" in str(e).lower():
                raise RetryableError(f"SAP ByD connection error: {e}")
            elif "not found" in str(e).lower():
                raise SAPIntegrationError(f"Sales order not found in SAP ByD: {e}")
            else:
                raise RetryableError(f"SAP ByD update failed: {e}")
        
        if success:
            # Update local delivery status code
            sales_order.delivery_status_code = status_code
            sales_order.metadata.update({
                'last_status_update': timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                'sap_status_updated': True,
                'previous_status': sales_order.delivery_status_code
            })
            sales_order.save()
            
            logger.info(f"Sales order {sales_order.sales_order_id} status successfully updated in SAP ByD")
        else:
            logger.error(f"Failed to update sales order {sales_order.sales_order_id} status in SAP ByD")
            raise RetryableError("SAP ByD returned failure for status update")
            
    except SalesOrder.DoesNotExist:
        logger.error(f"Sales order with ID {sales_order_id} not found")
        raise SAPIntegrationError(f"Sales order with ID {sales_order_id} not found")
    except (SAPIntegrationError, RetryableError):
        # Re-raise these specific exceptions for proper handling
        raise
    except Exception as e:
        logger.error(f"Unexpected error updating sales order {sales_order_id} status: {e}")
        raise SAPIntegrationError(f"Unexpected error: {e}")


@retry_on_failure(max_retries=3, delay=5)
def complete_transfer_in_sap(receipt_id: int):
    """
    Async task to complete a store-to-store transfer in SAP ByD
    This includes updating sales order status and linking goods issue documents
    """
    from byd_service.rest import RESTServices
    from .services import TransferReceiptService
    
    try:
        receipt = TransferReceiptNote.objects.get(id=receipt_id)
        sales_order = receipt.goods_issue.sales_order
        logger.info(f"Processing SAP transfer completion for receipt {receipt.receipt_number}")
        
        # Check if transfer is actually complete (all quantities received)
        delivery_status = sales_order.delivery_status
        if delivery_status[0] != '3':  # Not completely delivered
            logger.info(f"Transfer not complete for sales order {sales_order.sales_order_id}, status: {delivery_status[1]}")
            # Still update status to current state
            async_task('transfer_service.tasks.update_sales_order_status', sales_order.id)
            return
        
        # Initialize SAP ByD REST service
        try:
            byd_service = RESTServices()
        except Exception as e:
            logger.error(f"Failed to initialize SAP ByD service: {e}")
            raise RetryableError(f"SAP ByD service initialization failed: {e}")
        
        # Validate sales order has required data
        if not sales_order.object_id:
            raise SAPIntegrationError(f"Sales order {sales_order.sales_order_id} missing ObjectID")
        
        # Get goods issue SAP object ID from metadata if available
        goods_issue_object_id = receipt.goods_issue.metadata.get('sap_object_id')
        
        # Complete the transfer in SAP ByD
        logger.info(f"Completing transfer in SAP ByD for sales order {sales_order.sales_order_id}")
        try:
            result = byd_service.complete_transfer_in_sap(
                str(sales_order.sales_order_id),
                goods_issue_object_id
            )
        except Exception as e:
            logger.error(f"SAP ByD complete_transfer_in_sap failed: {e}")
            if "authentication" in str(e).lower() or "unauthorized" in str(e).lower():
                raise RetryableError(f"SAP ByD authentication error: {e}")
            elif "timeout" in str(e).lower() or "connection" in str(e).lower():
                raise RetryableError(f"SAP ByD connection error: {e}")
            elif "not found" in str(e).lower():
                raise SAPIntegrationError(f"Sales order not found in SAP ByD: {e}")
            else:
                raise RetryableError(f"SAP ByD complete transfer failed: {e}")
        
        # Validate response
        if not result or not result.get('success'):
            logger.error(f"Failed to complete transfer in SAP ByD: {result}")
            raise RetryableError("SAP ByD returned failure for transfer completion")
        
        # Update local sales order status and metadata
        sales_order.delivery_status_code = '3'  # Completely Delivered
        sales_order.metadata.update({
            'transfer_completed_date': timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            'sap_completion_response': result,
            'completed_by_receipt': receipt.receipt_number,
            'goods_issue_linked': goods_issue_object_id is not None
        })
        sales_order.save()
        
        # Update receipt metadata
        receipt.metadata.update({
            'sap_completion_response': result,
            'transfer_completed_date': timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        receipt.save()
        
        logger.info(f"Transfer successfully completed in SAP ByD for sales order {sales_order.sales_order_id}")
        
    except TransferReceiptNote.DoesNotExist:
        logger.error(f"Transfer receipt with ID {receipt_id} not found")
        raise SAPIntegrationError(f"Transfer receipt with ID {receipt_id} not found")
    except (SAPIntegrationError, RetryableError):
        # Re-raise these specific exceptions for proper handling
        raise
    except Exception as e:
        logger.error(f"Unexpected error completing transfer for receipt {receipt_id}: {e}")
        raise SAPIntegrationError(f"Unexpected error: {e}")