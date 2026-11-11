from django.db import models

class InventoryRestApiItem(models.Model):
    name = models.CharField(max_length=120)
    starts_at = models.DateTimeField(db_index=True)
    is_cancelled = models.BooleanField(default=False)

    class Meta:
        ordering = ['starts_at']
