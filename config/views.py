from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, F, IntegerField, When
from django.views.generic import TemplateView

from apps.tasks.models import Task, TaskPriority


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        priority_order = Case(
            When(priority=TaskPriority.LOW, then=1),
            When(priority=TaskPriority.NORMAL, then=2),
            When(priority=TaskPriority.HIGH, then=3),
            When(priority=TaskPriority.URGENT, then=4),
            default=0,
            output_field=IntegerField(),
        )
        context["priority_tasks"] = (
            Task.objects.filter(assignee=user, archived=False)
            .exclude(status__in=Task.TERMINAL_STATUSES)
            .annotate(priority_order=priority_order)
            .order_by(
                F("due_at").asc(nulls_last=True),
                F("priority_order").desc(),
                "-created_at",
            )[:3]
        )
        return context
