from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="mes/login.html", redirect_authenticated_user=True),
         name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("healthz", views.healthz, name="healthz"),
    path("", views.dashboard, name="dashboard"),
    path("board/", views.board, name="board"),
    path("jobs/", views.my_jobs, name="my_jobs"),
    path("orders/", views.customer_orders, name="customer_orders"),
    path("orders/<int:pk>/", views.customer_order, name="customer_order"),
    path("orders/<int:pk>/line/<int:line_id>/raise/", views.raise_work_order, name="raise_work_order"),
    path("traceability/", views.traceability, name="traceability"),
    path("tests/", views.test_reports, name="test_reports"),
    path("tests/<int:pk>/", views.test_report, name="test_report"),
    path("operator/<int:pk>/", views.operator, name="operator"),
    path("operator/<int:pk>/allocate/", views.allocate, name="allocate"),
    path("operator/<int:pk>/issue/", views.issue, name="issue"),
    path("operator/<int:pk>/assign/", views.assign, name="assign"),
    path("operator/<int:pk>/print/", views.print_sheet, name="print_sheet"),
    path("operator/<int:pk>/start/", views.start, name="start"),
    path("operator/<int:pk>/unit/", views.add_unit, name="add_unit"),
    path("operator/<int:pk>/unit/<int:unit_id>/retest/", views.retest_unit, name="retest_unit"),
    path("operator/<int:pk>/finish/", views.finish, name="finish"),
    path("operator/<int:pk>/approve/", views.approve, name="approve"),
    path("operator/<int:pk>/reject/", views.reject, name="reject"),
]

# Feature areas, each in its own module
urlpatterns += [
    path("", include("mes.urls_catalogue")),
    path("", include("mes.urls_bom")),
    path("", include("mes.urls_machines")),
    path("", include("mes.urls_planning")),
    path("", include("mes.urls_defects")),
    path("", include("mes.urls_data")),
]
