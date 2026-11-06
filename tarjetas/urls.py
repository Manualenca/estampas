from django.urls import path

from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("pedidos/nuevo/", views.pedido_form, name="pedido_nuevo"),
    path("pedidos/<int:pk>/", views.pedido_detalle, name="pedido_detalle"),
    path("pedidos/<int:pk>/editar/", views.pedido_form, name="pedido_editar"),
    path("pedidos/<int:pedido_pk>/estampas/nueva/", views.estampa_form, name="estampa_nueva"),
    path("estampas/<int:pk>/", views.vista_previa, name="vista_previa"),
    path("estampas/<int:pk>/editar/", views.estampa_form, name="estampa_editar"),
    path("estampas/<int:pk>/borrar/", views.estampa_borrar, name="estampa_borrar"),
    path(
        "estampas/<int:pk>/cuadros/<int:cuadro_pk>/",
        views.ajuste_cuadro,
        name="ajuste_cuadro",
    ),
    path("estampas/<int:pk>/posiciones/", views.posiciones, name="posiciones"),
    path("fuentes.css", views.fuentes_css, name="fuentes_css"),
    path("fuentes/<path:ruta>", views.fuente, name="fuente"),
]
