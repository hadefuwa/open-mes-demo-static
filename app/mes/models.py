import re
from datetime import date
from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone


class TimeStamped(models.Model):
    """created_at / updated_at on every record (shown in tables and detail pages)."""

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"updated_at"}
        super().save(*args, **kwargs)


class Product(TimeStamped):
    """One catalogue table for finished products, sub-assemblies and components.

    Codes follow a prefix + digits convention (FG1001, SA2001, ELE1001, FAS1001 ...).
    Everything is linked through BomLine, so any item can appear in any number of parents.
    """

    FINISHED, ASSEMBLY, COMPONENT = "finished", "assembly", "component"
    KIND_CHOICES = [(FINISHED, "Finished product"), (ASSEMBLY, "Assembly"), (COMPONENT, "Component")]

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=FINISHED)
    category = models.CharField(max_length=10, blank=True)  # code prefix: AU, HP, COM, FIX, LAS, PCB ...
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)  # purchase cost
    rrp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # recommended retail price
    rrp_estimated = models.BooleanField(default=False)  # True when the RRP was derived from cost, not a price list
    range_name = models.CharField(max_length=60, blank=True)  # product range / price-list section
    free_stock = models.IntegerField(null=True, blank=True)  # units in stock and unallocated
    reorder_level = models.PositiveIntegerField(null=True, blank=True)
    supplier_code = models.CharField(max_length=30, blank=True)  # supplier account code
    supplier_part_no = models.CharField(max_length=60, blank=True)
    erp_type = models.CharField(max_length=30, blank=True)  # the ERP's own classification, e.g. "Finished Goods"
    standard_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)  # ERP standard cost, for comparison
    stock_quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # on hand
    is_stocked = models.BooleanField(default=True)  # False for non-stock items
    revision = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def margin(self):
        """RRP minus total cost to manufacture, or None when there is no RRP."""
        return None if self.rrp is None else self.rrp - self.total_cost

    @property
    def low_stock(self):
        """True when stock is known and at or below the re-order level (on hand if known, else free stock)."""
        on_hand = self.stock_quantity if self.stock_quantity is not None else self.free_stock
        return (on_hand is not None and self.reorder_level is not None
                and self.reorder_level > 0 and on_hand <= self.reorder_level)

    @property
    def cost_variance(self):
        """ERP standard cost minus the cost rolled up from our BOM, or None when either is unknown."""
        if self.standard_cost is None or not self.bom_lines.exists():
            return None
        return self.standard_cost - self.bom_cost

    @property
    def margin_pct(self):
        return None if not self.rrp else round(100 * self.margin / self.rrp, 1)

    def save(self, *args, **kwargs):
        if not self.category:
            match = re.match(r"[A-Za-z]+", self.code)
            self.category = match.group().upper() if match else ""
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        name = "component_detail" if self.kind == self.COMPONENT else "product_detail"
        return reverse(name, args=[self.pk])

    # Derived figures (see mes/costing.py)
    @property
    def build_minutes(self):
        from . import costing
        return costing.total_build_minutes(self)

    @property
    def bom_cost(self):
        from . import costing
        return costing.bom_cost(self)

    @property
    def total_cost(self):
        from . import costing
        return costing.total_cost(self)


class Workstation(TimeStamped):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class ProductionTechnician(TimeStamped):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class BomLine(TimeStamped):
    """parent is made from `quantity` x child. The relational link between catalogue items."""

    parent = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="bom_lines")
    child = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="used_in")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1"))
    sequence = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["parent__code", "sequence", "child__code"]
        constraints = [models.UniqueConstraint(fields=["parent", "child"], name="unique_bom_line")]

    def __str__(self):
        return f"{self.parent.code} > {self.child.code} x{self.quantity}"

    def clean(self):
        from django.core.exceptions import ValidationError
        from . import costing
        if self.parent_id and self.child_id and (
                self.parent_id == self.child_id or costing.would_create_cycle(self.parent, self.child)):
            raise ValidationError("A BOM cannot contain itself, directly or indirectly.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Machine(TimeStamped):
    AVAILABLE, IN_USE, MAINTENANCE, DOWN = "available", "in_use", "maintenance", "down"
    STATUS_CHOICES = [(AVAILABLE, "Available"), (IN_USE, "In use"), (MAINTENANCE, "Maintenance"), (DOWN, "Down")]

    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=60, blank=True)  # e.g. Laser, Press, Test rig
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=AVAILABLE)
    location = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_available(self):
        return self.status in (self.AVAILABLE, self.IN_USE)


class RoutingStep(TimeStamped):
    """One manufacturing operation for a product, optionally needing a machine."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="routing_steps")
    sequence = models.PositiveIntegerField(default=10)
    name = models.CharField(max_length=120)
    machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="routing_steps")
    minutes = models.DecimalField(max_digits=7, decimal_places=1, default=Decimal("0"))

    class Meta:
        ordering = ["product__code", "sequence"]

    def __str__(self):
        return f"{self.product.code} {self.sequence} {self.name}"


class WorkOrder(TimeStamped):
    # Lifecycle mirrors the paper process: planner enters the order, stock is
    # allocated then issued (kitting), the technician builds and tests, the
    # team leader signs off QA, then the order is completed.
    ENTERED, ALLOCATED, ISSUED, IN_PROGRESS, QA, COMPLETE = (
        "entered", "allocated", "issued", "in_progress", "qa", "complete")
    STATUS_CHOICES = [
        (ENTERED, "Entered"),
        (ALLOCATED, "Allocated"),
        (ISSUED, "Issued"),
        (IN_PROGRESS, "In progress"),
        (QA, "QA"),
        (COMPLETE, "Complete"),
    ]

    number = models.CharField(max_length=30, unique=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    workstation = models.ForeignKey(Workstation, on_delete=models.PROTECT, null=True, blank=True)
    technician = models.ForeignKey(ProductionTechnician, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="work_orders")
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ENTERED)
    printed = models.BooleanField(default=False)
    # Estimated labour minutes for the whole order.
    est_minutes = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["due_date", "number"]

    def __str__(self):
        return self.number

    @property
    def units_recorded(self):
        count = getattr(self, "unit_count", None)  # set by the board's annotated query
        return self.units.count() if count is None else count

    @property
    def progress_pct(self):
        if not self.quantity:
            return 0
        return min(100, round(100 * self.units_recorded / self.quantity))

    @property
    def is_overdue(self):
        return bool(self.due_date and self.status != self.COMPLETE and self.due_date < date.today())

    @property
    def due_soon(self):
        return bool(self.due_date and self.status != self.COMPLETE
                    and 0 <= (self.due_date - date.today()).days <= 2)


class CustomerOrder(TimeStamped):
    """A customer's order. Lines are fulfilled by raising works orders."""

    number = models.CharField(max_length=30, unique=True)
    order_date = models.DateField()
    ship_date = models.DateField(null=True, blank=True)
    customer = models.CharField(max_length=200)
    customer_ref = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-order_date", "-number"]

    def __str__(self):
        return self.number


class CustomerOrderLine(TimeStamped):
    order = models.ForeignKey(CustomerOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sales_lines")
    quantity = models.PositiveIntegerField()
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="order_lines")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.order} {self.product.code} x{self.quantity}"


class Unit(TimeStamped):
    """One serialised unit built under a work order."""

    PENDING, PASS, REWORK, SCRAP = "pending", "pass", "rework", "scrap"
    RESULT_CHOICES = [
        (PENDING, "Pending"),
        (PASS, "Pass"),
        (REWORK, "Rework"),
        (SCRAP, "Scrap"),
    ]

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="units")
    serial = models.CharField(max_length=50, unique=True)
    result = models.CharField(max_length=20, choices=RESULT_CHOICES, default=PENDING)
    reason = models.CharField(max_length=200, blank=True)
    first_pass = models.BooleanField(default=True)  # cleared if a unit ever fails

    def __str__(self):
        return self.serial


class Defect(TimeStamped):
    """A recorded defect or scrap: which part, on which build, how many wasted, at what cost."""

    occurred_at = models.DateTimeField(default=timezone.now)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="defects")  # product being built
    component = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="defects_as_component")  # the defective part
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="defects")
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name="defects")
    quantity = models.PositiveIntegerField(default=1)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))  # cost at the time
    description = models.CharField(max_length=300)
    reported_by = models.ForeignKey(ProductionTechnician, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="defects")

    class Meta:
        ordering = ["-occurred_at", "-id"]

    def __str__(self):
        return f"Defect {self.pk}: {self.description}"

    @property
    def cost(self):
        return self.unit_cost * self.quantity


class TestReport(TimeStamped):
    """A completed test procedure for one built unit (imported from a test-report workbook)."""

    PASS, FAIL = "PASS", "FAIL"

    report_id = models.CharField(max_length=60, unique=True)
    procedure = models.CharField(max_length=30)  # e.g. a document/procedure code
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="test_reports")
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="test_reports")
    serial = models.CharField(max_length=50)
    build_reference = models.CharField(max_length=50, blank=True)
    operator_name = models.CharField(max_length=100, blank=True)
    technician = models.ForeignKey(ProductionTechnician, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="test_reports")
    test_date = models.DateField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    overall_result = models.CharField(max_length=10, default=PASS)
    comments = models.TextField(blank=True)

    class Meta:
        ordering = ["-test_date", "-submitted_at", "report_id"]

    def __str__(self):
        return self.report_id

    @property
    def tester(self):
        return self.technician.name if self.technician else self.operator_name

    @property
    def passed(self):
        return self.overall_result == self.PASS


class TestStep(models.Model):
    report = models.ForeignKey(TestReport, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField()
    section = models.CharField(max_length=120)
    number = models.CharField(max_length=10)
    criteria = models.TextField()
    result = models.CharField(max_length=10, blank=True)
    comments = models.TextField(blank=True)
    sign_off = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["order"]


class Event(models.Model):
    """Append-only audit trail. `source` is the hook for future machine data."""

    OPERATOR, ERP, SYSTEM = "operator", "erp", "system"

    timestamp = models.DateTimeField(auto_now_add=True)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="events")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, null=True, blank=True, related_name="events")
    action = models.CharField(max_length=50)
    detail = models.CharField(max_length=300, blank=True)
    source = models.CharField(max_length=20, default=OPERATOR)
    actor = models.CharField(max_length=150, blank=True)  # username of whoever did it, when login is on

    class Meta:
        ordering = ["timestamp", "id"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.work_order} {self.action}"

    def save(self, *args, **kwargs):
        if not self.actor:
            from .middleware import current_user
            user = current_user.get()
            if user is not None:
                self.actor = user.get_username()
        super().save(*args, **kwargs)
