from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils.timezone import now

class ByDPostingStatus(models.Model):
    """
    Tracks the status of data postings to SAP ByDesign (ByD).
    """
    # Generic foreign key to reference any model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    related_object = GenericForeignKey('content_type', 'object_id')
    # Status of the posting
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # JSON field to store the response from ByD
    response_data = models.JSONField(null=True, blank=True)
    # Error message in case of failure
    error_message = models.TextField(null=True, blank=True)
    # Additional fields for audit or tracking
    request_payload = models.JSONField(null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)

    def mark_success(self, response: dict):
        """
            Marks the posting as successful and saves the response.
        """
        self.status = 'success'
        self.response_data = response
        self.error_message = ""
        self.save()

    def mark_failure(self, error: str):
        """
            Marks the posting as failed and records the error message.
        """
        self.status = 'failed'
        self.error_message = error
        self.save()

    def increment_retry(self):
        """
            Increments the retry count for the posting.
        """
        self.retry_count += 1
        self.save()

    def __str__(self):
        return f"Posting for {self.related_object} | Status: {self.get_status_display()} | On {str(self.created_at).split(' ')[0]}"
    
    class Meta:
        verbose_name_plural = "Posting Reports"


def get_or_create_byd_posting_status(instance, request_payload=None):
    """
    Retrieve an existing ByDPostingStatus record or create a new one.

    Args:
        instance (models.Model): The related object being posted to ByD.
        request_payload (dict, optional): Payload for the ByD request. Defaults to None.

    Returns:
        ByDPostingStatus: The retrieved or newly created record.
    """
    content_type = ContentType.objects.get_for_model(instance)
    obj_id = instance.id

    # Retrieve or create the ByDPostingStatus
    posting_status, created = ByDPostingStatus.objects.get_or_create(
        content_type=content_type,
        object_id=obj_id,
        defaults={
            'status': 'pending',
            'request_payload': request_payload,
        }
    )

    # Update the request payload if the record already exists
    if not created and request_payload:
        posting_status.request_payload = request_payload
        posting_status.save()

    return posting_status