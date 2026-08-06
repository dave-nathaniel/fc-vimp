from django.db import migrations, models
from django.db.models import Count


def dedupe_posting_status(apps, schema_editor):
    """
        Collapse duplicate ByDPostingStatus rows for the same
        (content_type, object_id, django_q_task_name) down to one, so the
        unique constraint added below can be applied.

        Keeper preference: a 'success' row wins (it is what the tasks'
        idempotency guard checks), otherwise the most recently updated row.
        The keeper inherits the highest retry_count in the group so the
        retry cap keeps its meaning.
    """
    ByDPostingStatus = apps.get_model('byd_service', 'ByDPostingStatus')

    duplicate_groups = (
        ByDPostingStatus.objects
        .values('content_type_id', 'object_id', 'django_q_task_name')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
    )

    for group in duplicate_groups:
        group_filter = {
            'content_type_id': group['content_type_id'],
            'object_id': group['object_id'],
            'django_q_task_name': group['django_q_task_name'],
        }
        rows = list(
            ByDPostingStatus.objects.filter(**group_filter)
            .order_by('-updated_at', '-id')
        )
        successes = [row for row in rows if row.status == 'success']
        keeper = successes[0] if successes else rows[0]

        max_retry_count = max(row.retry_count for row in rows)
        if keeper.retry_count != max_retry_count:
            keeper.retry_count = max_retry_count
            keeper.save(update_fields=['retry_count'])

        ByDPostingStatus.objects.filter(**group_filter).exclude(pk=keeper.pk).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('byd_service', '0003_bydpostingstatus_django_q_task_name'),
    ]

    operations = [
        migrations.RunPython(dedupe_posting_status, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name='bydpostingstatus',
            options={'verbose_name': '6.1 Posting Report', 'verbose_name_plural': '6.1 Posting Reports'},
        ),
        migrations.AddConstraint(
            model_name='bydpostingstatus',
            constraint=models.UniqueConstraint(
                fields=('content_type', 'object_id', 'django_q_task_name'),
                name='uniq_byd_posting_per_object_task',
            ),
        ),
    ]
