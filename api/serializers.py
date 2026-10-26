from rest_framework import serializers

from agencies.models import CustomField, OfferInstallment, ServiceOffer
from dossiers.models import DocumentRequest, Dossier, DossierStage, Payment, ServiceFee, WorkflowTemplate


class StudentSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField(allow_blank=True)


class StageSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = DossierStage
        fields = ["order", "name", "status", "status_label", "due_date", "started_at", "completed_at"]


class DocumentSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    stage = serializers.CharField(source="stage.name", default=None, read_only=True)

    class Meta:
        model = DocumentRequest
        fields = ["id", "name", "description", "is_required", "status", "status_label", "due_date",
                  "rejection_reason", "stage"]


class FeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceFee
        fields = ["id", "label", "amount", "due_date", "created_at"]


class PaymentSerializer(serializers.ModelSerializer):
    method_label = serializers.CharField(source="get_method_display", read_only=True)
    dossier = serializers.CharField(source="dossier.reference", read_only=True)
    cancelled = serializers.BooleanField(source="is_cancelled", read_only=True)

    class Meta:
        model = Payment
        fields = ["receipt_number", "dossier", "amount", "method", "method_label", "reference", "paid_on",
                  "recorded_at", "cancelled", "cancellation_reason"]


class DossierListSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    student = StudentSerializer(read_only=True)
    counselor_email = serializers.EmailField(source="counselor.email", default=None, read_only=True)
    current_stage = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Dossier
        fields = ["reference", "status", "status_label", "student", "destination_country", "destination_city",
                  "institution", "program", "intake", "counselor_email", "current_stage", "progress_percent",
                  "balance", "created_at", "updated_at"]

    def get_current_stage(self, obj) -> dict | None:
        stage = obj.current_stage
        return {"name": stage.name, "due_date": stage.due_date} if stage else None

    def get_progress_percent(self, obj) -> int:
        return obj.progress_percent()

    def get_balance(self, obj) -> str:
        return str(obj.balance())


class DossierDetailSerializer(DossierListSerializer):
    stages = StageSerializer(many=True, read_only=True)
    documents = DocumentSerializer(source="document_requests", many=True, read_only=True)
    fees = FeeSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    alerts = serializers.SerializerMethodField()

    class Meta(DossierListSerializer.Meta):
        fields = DossierListSerializer.Meta.fields + [
            "guardian_name", "guardian_phone", "blocked_reason", "custom_data", "alerts",
            "stages", "documents", "fees", "payments",
        ]

    def get_alerts(self, obj) -> list[dict]:
        return [{"code": a["code"], "label": a["label"]} for a in obj.alerts()]


class DossierCreateSerializer(serializers.Serializer):
    student_email = serializers.EmailField()
    student_first_name = serializers.CharField(max_length=150)
    student_last_name = serializers.CharField(max_length=150)
    student_phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    workflow_id = serializers.IntegerField(help_text="Identifiant d'un parcours (voir /workflows/).")
    counselor_email = serializers.EmailField(required=False)
    offer_id = serializers.IntegerField(required=False, help_text="Prestation à appliquer (voir /offers/).")
    destination_country = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    destination_city = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    institution = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    program = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    intake = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    guardian_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    guardian_phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    custom_data = serializers.DictField(required=False, default=dict)


class DossierUpdateSerializer(serializers.Serializer):
    destination_country = serializers.CharField(max_length=100, required=False)
    destination_city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    institution = serializers.CharField(max_length=200, required=False, allow_blank=True)
    program = serializers.CharField(max_length=200, required=False, allow_blank=True)
    intake = serializers.CharField(max_length=50, required=False, allow_blank=True)
    guardian_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    guardian_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    custom_data = serializers.DictField(required=False)


class AdvanceSerializer(serializers.Serializer):
    next_due_date = serializers.DateField(required=False, allow_null=True)


class StatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Dossier.Status.choices)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class PaymentCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=0, min_value=1)
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    paid_on = serializers.DateField(required=False, allow_null=True)


class DocumentRequestCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    is_required = serializers.BooleanField(required=False, default=True)
    due_date = serializers.DateField(required=False, allow_null=True)


class ApplyOfferSerializer(serializers.Serializer):
    offer_id = serializers.IntegerField()


class InstallmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfferInstallment
        fields = ["label", "amount", "due_after_days"]


class OfferSerializer(serializers.ModelSerializer):
    installments = InstallmentSerializer(many=True, read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=0, read_only=True)

    class Meta:
        model = ServiceOffer
        fields = ["id", "name", "description", "destination_country", "total", "installments"]


class WorkflowSerializer(serializers.ModelSerializer):
    stages = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowTemplate
        fields = ["id", "name", "destination_country", "stages"]

    def get_stages(self, obj) -> list[str]:
        return [s.name for s in obj.stages.all()]


class CustomFieldSerializer(serializers.ModelSerializer):
    choices = serializers.ListField(source="choice_list", read_only=True)

    class Meta:
        model = CustomField
        fields = ["key", "label", "field_type", "required", "choices", "help_text"]
