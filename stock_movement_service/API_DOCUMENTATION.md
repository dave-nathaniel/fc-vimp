# Stock Movement Service API Documentation

## Overview

The Stock Movement Service provides a comprehensive REST API for managing store-to-store transfers within the Food Concepts ecosystem. The service handles the complete transfer workflow from sales order management through goods issue and transfer receipt processes.

## Base URL

```
/stock-movement/v1/
```

## Authentication

All endpoints require authentication using the `CombinedAuthentication` system (JWT + ADFS). Include the Bearer token in the Authorization header:

```
Authorization: Bearer <your-token>
```

## Data Models

### Sales Order
Represents a transfer order from SAP ByD for store-to-store transfers.

### Goods Issue Note
Records goods dispatched from source stores.

### Transfer Receipt Note
Records goods received at destination stores.

### Store Authorization
Links users to authorized stores with specific roles.

---

## API Endpoints

### 1. Sales Orders

#### GET /sales-orders
Get all sales orders for user's authorized stores.

**Response:**
```json
{
  "success": true,
  "message": "Sales Orders Retrieved",
  "data": {
    "count": 25,
    "next": "http://example.com/stock-movement/v1/sales-orders?page=2",
    "previous": null,
    "results": [
      {
        "object_id": "00163E0B8E951EEF8AAD6D0C0F8B0001",
        "sales_order_id": 59461,
        "source_store": {
          "id": 1,
          "store_name": "Main Store",
          "icg_warehouse_code": "MAIN001",
          "byd_cost_center_code": "STORE001"
        },
        "destination_store": {
          "id": 2,
          "store_name": "Branch Store",
          "icg_warehouse_code": "BRANCH001",
          "byd_cost_center_code": "STORE002"
        },
        "total_net_amount": "15000.500",
        "order_date": "2023-12-01",
        "delivery_status_code": "1",
        "delivery_status_text": "Not Delivered",
        "delivery_completed": false,
        "line_items": [
          {
            "object_id": "00163E0B8E951EEF8AAD6D0C0F8B0002",
            "product_id": "PROD001",
            "product_name": "Premium Coffee Beans",
            "quantity": "100.000",
            "unit_price": "150.00",
            "unit_of_measurement": "KG",
            "delivery_status_code": "1",
            "delivery_status_text": "Not Delivered",
            "issued_quantity": 0.0,
            "received_quantity": 0.0,
            "delivery_outstanding_quantity": 100.0,
            "delivery_completed": false,
            "metadata": {},
            "goods_issue_items": []
          }
        ],
        "metadata": {}
      }
    ]
  }
}
```

#### GET /sales-orders/{sales_order_id}
Get a specific sales order by ID.

**Parameters:**
- `sales_order_id` (integer): The sales order ID

**Response:**
```json
{
  "success": true,
  "message": "Sales Order Retrieved",
  "data": {
    "object_id": "00163E0B8E951EEF8AAD6D0C0F8B0001",
    "sales_order_id": 59461,
    "source_store": {...},
    "destination_store": {...},
    "total_net_amount": "15000.500",
    "order_date": "2023-12-01",
    "delivery_status_code": "1",
    "delivery_status_text": "Not Delivered",
    "delivery_completed": false,
    "line_items": [...],
    "metadata": {}
  }
}
```

**Error Responses:**
- `404 NOT FOUND`: Sales order not found
- `403 FORBIDDEN`: User doesn't have access to this sales order

---

### 2. Goods Issue

#### POST /goods-issue
Create a goods issue note to dispatch items from source store.

**Request Body:**
```json
{
  "sales_order_id": 59461,
  "issued_goods": [
    {
      "itemObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0002",
      "productID": "PROD001",
      "quantityIssued": "50.000"
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Goods Issue Created",
  "data": {
    "issue_number": 594612,
    "sales_order": {
      "sales_order_id": 59461,
      "source_store": {...},
      "destination_store": {...}
    },
    "source_store": {...},
    "created_date": "2023-12-01",
    "created_by": "John Doe",
    "total_issued_value": 7500.0,
    "posted_to_icg": false,
    "posted_to_sap": false,
    "line_items": [
      {
        "id": 1,
        "sales_order_line_item": {...},
        "quantity_issued": "50.000",
        "issued_value": 7500.0,
        "received_quantity": 0.0,
        "metadata": {},
        "receipt_items": []
      }
    ],
    "metadata": {}
  }
}
```

**Error Responses:**
- `400 BAD REQUEST`: Invalid input data or insufficient inventory
- `403 FORBIDDEN`: User doesn't have access to source store
- `404 NOT FOUND`: Sales order not found

#### GET /goods-issues
Get all goods issue notes for user's authorized stores.

**Response:**
```json
{
  "success": true,
  "message": "Goods Issues Retrieved",
  "data": {
    "count": 15,
    "next": null,
    "previous": null,
    "results": [...]
  }
}
```

#### GET /goods-issues/{issue_number}
Get a specific goods issue note.

**Parameters:**
- `issue_number` (integer): The goods issue number

**Response:**
```json
{
  "success": true,
  "message": "Goods Issue Retrieved",
  "data": {
    "issue_number": 594612,
    "sales_order": {...},
    "source_store": {...},
    "created_date": "2023-12-01",
    "created_by": "John Doe",
    "total_issued_value": 7500.0,
    "posted_to_icg": false,
    "posted_to_sap": false,
    "line_items": [...],
    "metadata": {}
  }
}
```

---

### 3. Transfer Receipt

#### POST /transfer-receipt
Create a transfer receipt note to record goods received at destination store.

**Request Body:**
```json
{
  "goods_issue_number": 594612,
  "received_goods": [
    {
      "itemObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0002",
      "quantityReceived": "45.000"
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Transfer Receipt Created",
  "data": {
    "receipt_number": 594613,
    "goods_issue": {
      "issue_number": 594612,
      "sales_order": {...}
    },
    "destination_store": {...},
    "created_date": "2023-12-01",
    "created_by": "Jane Smith",
    "total_received_value": 6750.0,
    "posted_to_icg": false,
    "line_items": [
      {
        "id": 1,
        "goods_issue_line_item": {...},
        "quantity_received": "45.000",
        "received_value": 6750.0,
        "metadata": {}
      }
    ],
    "metadata": {}
  }
}
```

**Error Responses:**
- `400 BAD REQUEST`: Invalid input data or quantity exceeds issued amount
- `403 FORBIDDEN`: User doesn't have access to destination store
- `404 NOT FOUND`: Goods issue note not found

#### GET /transfer-receipts
Get all transfer receipt notes for user's authorized stores.

#### GET /transfer-receipts/{receipt_number}
Get a specific transfer receipt note.

---

### 4. Pending Operations

#### GET /pending-issues
Get sales orders that are pending goods issue for user's source stores.

**Response:**
```json
{
  "success": true,
  "message": "Pending Issues Retrieved",
  "data": {
    "count": 5,
    "results": [
      {
        "sales_order_id": 59462,
        "source_store": {...},
        "destination_store": {...},
        "delivery_status_code": "1",
        "delivery_status_text": "Not Delivered",
        "line_items": [...]
      }
    ]
  }
}
```

#### GET /pending-receipts
Get goods issues that are pending receipt for user's destination stores.

**Response:**
```json
{
  "success": true,
  "message": "Pending Receipts Retrieved",
  "data": {
    "count": 3,
    "results": [
      {
        "issue_number": 594612,
        "sales_order": {...},
        "source_store": {...},
        "created_date": "2023-12-01",
        "line_items": [...]
      }
    ]
  }
}
```

---

### 5. Reports and Summary

#### GET /transfer-summary
Get transfer summary statistics for user's authorized stores.

**Response:**
```json
{
  "success": true,
  "message": "Transfer Summary Retrieved",
  "data": [
    {
      "store": {
        "id": 1,
        "store_name": "Main Store",
        "icg_warehouse_code": "MAIN001"
      },
      "total_outbound_orders": 25,
      "total_inbound_orders": 18,
      "pending_issues": 5,
      "pending_receipts": 3,
      "total_value_issued": "125000.00",
      "total_value_received": "98000.00"
    }
  ]
}
```

---

### 6. User Authorization

#### GET /user-store-authorizations
Get store authorizations for the current user.

**Response:**
```json
{
  "success": true,
  "message": "Store Authorizations Retrieved",
  "data": [
    {
      "id": 1,
      "user": "John Doe (john@example.com)",
      "store": {
        "id": 1,
        "store_name": "Main Store",
        "icg_warehouse_code": "MAIN001"
      },
      "role": "manager",
      "created_date": "2023-11-01T10:00:00Z",
      "metadata": {}
    }
  ]
}
```

---

## Status Codes

### Delivery Status Codes
- `1`: Not Delivered
- `2`: Partially Delivered  
- `3`: Completely Delivered

### Store Roles
- `manager`: Store Manager
- `assistant`: Store Assistant
- `admin`: Administrator

---

## Error Handling

All API endpoints return standardized error responses:

```json
{
  "success": false,
  "message": "User-friendly error message",
  "error_code": "SPECIFIC_ERROR_CODE",
  "details": {
    "field_errors": {},
    "validation_errors": []
  }
}
```

### Common HTTP Status Codes
- `200 OK`: Request successful
- `201 CREATED`: Resource created successfully
- `400 BAD REQUEST`: Invalid request data
- `401 UNAUTHORIZED`: Authentication required
- `403 FORBIDDEN`: Insufficient permissions
- `404 NOT FOUND`: Resource not found
- `500 INTERNAL SERVER ERROR`: Server error

---

## Usage Examples

### Complete Transfer Workflow

1. **Get Available Sales Orders**
```bash
curl -X GET \
  "/stock-movement/v1/sales-orders" \
  -H "Authorization: Bearer <token>"
```

2. **Create Goods Issue**
```bash
curl -X POST \
  "/stock-movement/v1/goods-issue" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "sales_order_id": 59461,
    "issued_goods": [
      {
        "itemObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0002",
        "productID": "PROD001",
        "quantityIssued": "50.000"
      }
    ]
  }'
```

3. **Create Transfer Receipt**
```bash
curl -X POST \
  "/stock-movement/v1/transfer-receipt" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "goods_issue_number": 594612,
    "received_goods": [
      {
        "itemObjectID": "00163E0B8E951EEF8AAD6D0C0F8B0002",
        "quantityReceived": "45.000"
      }
    ]
  }'
```

### Check Store Summary
```bash
curl -X GET \
  "/stock-movement/v1/transfer-summary" \
  -H "Authorization: Bearer <token>"
```

---

## Integration Notes

### External System Integration
- **SAP ByD**: Sales orders are fetched and updated via REST API
- **ICG Inventory**: Inventory levels are updated for goods issue and receipt
- **Async Processing**: External system updates are handled asynchronously using Django-Q

### Mock Data
The service includes mock data for sales orders 59461, 59462, and 59463 for testing purposes. These contain sample products and store mappings.

### Validation Rules
- Goods issue quantities cannot exceed sales order quantities
- Transfer receipt quantities cannot exceed goods issue quantities
- Users can only access stores they are authorized for
- All quantities must be positive numbers

---

## Support

For technical support or questions about the Stock Movement Service API, please contact the development team.