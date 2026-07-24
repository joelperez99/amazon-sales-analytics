"""Gráficas interactivas con Plotly.

Criterios de diseño aplicados en todo el módulo
-----------------------------------------------
* **Un solo eje.** Nunca hay dos escalas verticales en la misma gráfica: dos
  medidas de magnitud distinta se muestran en dos gráficas separadas.
* **El color sigue a la entidad, no a su posición.** «Ventas» siempre es azul y
  «Tarifas» siempre es naranja, cambien o no los filtros.
* **Paleta ordenada.** Los colores categóricos se asignan en el orden validado
  para daltonismo y jamás se reciclan: a partir del octavo, el resto se agrupa
  en «Otros».
* **Marcas delgadas y rejilla discreta**: la tinta se reserva para los datos.
* **Etiquetas directas selectivas**: no se pone un número sobre cada punto.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from utils.constants import (
    COLOR_CRITICO,
    COLOR_EJE,
    COLOR_IMPUESTOS,
    COLOR_NETO,
    COLOR_PEDIDOS,
    COLOR_REEMBOLSOS,
    COLOR_REJILLA,
    COLOR_SUPERFICIE,
    COLOR_TARIFAS,
    COLOR_TINTA,
    COLOR_TINTA_SECUNDARIA,
    COLOR_TINTA_TENUE,
    COLOR_UNIDADES,
    COLOR_VENTAS,
    FUENTE_UI,
    PALETA_CATEGORICA,
    RAMPA_SECUENCIAL,
)

#: Máximo de series categóricas antes de agrupar en «Otros».
MAX_SERIES = 8


# =============================================================================
# Base común
# =============================================================================


def _figura_base(alto: int = 380, mostrar_leyenda: bool = False) -> go.Figure:
    """Figura con el cromo del tablero ya aplicado."""
    figura = go.Figure()
    figura.update_layout(
        height=alto,
        paper_bgcolor=COLOR_SUPERFICIE,
        plot_bgcolor=COLOR_SUPERFICIE,
        font=dict(family=FUENTE_UI, size=13, color=COLOR_TINTA_SECUNDARIA),
        margin=dict(l=10, r=16, t=40, b=10),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=COLOR_SUPERFICIE,
            bordercolor=COLOR_EJE,
            font=dict(family=FUENTE_UI, size=12, color=COLOR_TINTA),
        ),
        showlegend=mostrar_leyenda,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=12), bgcolor="rgba(0,0,0,0)",
        ),
        separators=".,",  # punto decimal, coma de millares (convención de México)
    )
    figura.update_xaxes(
        showgrid=False,
        showline=True, linecolor=COLOR_EJE, linewidth=1,
        tickfont=dict(color=COLOR_TINTA_TENUE, size=11),
        title_font=dict(color=COLOR_TINTA_TENUE, size=12),
    )
    figura.update_yaxes(
        showgrid=True, gridcolor=COLOR_REJILLA, gridwidth=1,
        zeroline=True, zerolinecolor=COLOR_EJE, zerolinewidth=1,
        showline=False,
        tickfont=dict(color=COLOR_TINTA_TENUE, size=11),
        title_font=dict(color=COLOR_TINTA_TENUE, size=12),
    )
    return figura


def _titulo(figura: go.Figure, texto: str, subtitulo: str = "") -> go.Figure:
    """Aplica el título (y un subtítulo opcional en tinta secundaria)."""
    completo = texto
    if subtitulo:
        completo = f"{texto}<br><span style='font-size:12px;color:{COLOR_TINTA_TENUE}'>{subtitulo}</span>"
    figura.update_layout(
        title=dict(
            text=completo, x=0, xanchor="left", y=0.97, yanchor="top",
            font=dict(size=15, color=COLOR_TINTA),
        ),
        margin=dict(l=10, r=16, t=60 if subtitulo else 44, b=10),
    )
    return figura


def _agrupar_en_otros(
    df: pd.DataFrame, columna_etiqueta: str, columna_valor: str, maximo: int = MAX_SERIES
) -> pd.DataFrame:
    """Conserva las ``maximo`` categorías mayores y suma el resto en «Otros».

    Evita que una gráfica genere colores fuera de la paleta validada.
    """
    if len(df) <= maximo:
        return df
    ordenado = df.sort_values(columna_valor, ascending=False)
    principales = ordenado.head(maximo - 1).copy()
    resto = ordenado.tail(len(ordenado) - (maximo - 1))
    fila_otros = {columna_etiqueta: f"Otros ({len(resto)})", columna_valor: resto[columna_valor].sum()}
    for columna in df.columns:
        if columna not in fila_otros:
            fila_otros[columna] = (
                resto[columna].sum() if pd.api.types.is_numeric_dtype(resto[columna]) else ""
            )
    return pd.concat([principales, pd.DataFrame([fila_otros])], ignore_index=True)


_FORMATO_MONEDA_HOVER = "$%{y:,.2f} MXN"
_PLANTILLA_MONEDA = "<b>%{x}</b><br>%{fullData.name}: $%{y:,.2f} MXN<extra></extra>"
_PLANTILLA_ENTERO = "<b>%{x}</b><br>%{fullData.name}: %{y:,.0f}<extra></extra>"


def figura_vacia(mensaje: str = "No hay datos para mostrar con los filtros actuales.") -> go.Figure:
    """Figura de reemplazo cuando una gráfica se queda sin datos."""
    figura = _figura_base(alto=260)
    figura.add_annotation(
        text=mensaje, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5,
        font=dict(size=14, color=COLOR_TINTA_TENUE),
    )
    figura.update_xaxes(visible=False)
    figura.update_yaxes(visible=False)
    return figura


# =============================================================================
# Evolución temporal
# =============================================================================


def linea_temporal(
    serie: pd.DataFrame,
    columna: str,
    titulo: str,
    color: str = COLOR_VENTAS,
    es_moneda: bool = True,
    nombre_serie: str = "",
) -> go.Figure:
    """Línea de evolución de una métrica en el tiempo.

    Una sola serie no lleva leyenda: el título ya la nombra.
    """
    if serie.empty or columna not in serie.columns:
        return figura_vacia()

    figura = _figura_base()
    etiqueta = nombre_serie or titulo

    figura.add_trace(go.Scatter(
        x=serie["periodo"],
        y=serie[columna],
        mode="lines",
        name=etiqueta,
        line=dict(color=color, width=2, shape="linear"),
        fill="tozeroy",
        fillcolor=_con_alfa(color, 0.10),
        hovertemplate=(
            "<b>%{x|%d/%m/%Y}</b><br>" +
            (f"{etiqueta}: $%{{y:,.2f}} MXN" if es_moneda else f"{etiqueta}: %{{y:,.0f}}") +
            "<extra></extra>"
        ),
    ))

    # Etiqueta directa sobre el último punto: orienta sin saturar.
    if len(serie) > 1:
        ultimo = serie.iloc[-1]
        valor = ultimo[columna]
        texto = f"${valor:,.0f}" if es_moneda else f"{valor:,.0f}"
        figura.add_trace(go.Scatter(
            x=[ultimo["periodo"]], y=[valor], mode="markers+text",
            marker=dict(size=8, color=color),
            text=[texto], textposition="middle right",
            textfont=dict(size=12, color=COLOR_TINTA_SECUNDARIA),
            hoverinfo="skip", showlegend=False, cliponaxis=False,
        ))

    figura.update_yaxes(tickprefix="$" if es_moneda else "", tickformat=",.0f")
    return _titulo(figura, titulo)


def lineas_comparadas(
    serie: pd.DataFrame, columna: str, titulo: str, es_moneda: bool = True
) -> go.Figure:
    """Superpone el periodo actual y el anterior alineados por número de día."""
    if serie.empty or "periodo_etiqueta" not in serie.columns:
        return figura_vacia()

    figura = _figura_base(mostrar_leyenda=True)
    colores = {"Periodo actual": COLOR_VENTAS, "Periodo anterior": COLOR_TINTA_TENUE}

    for etiqueta in ("Periodo anterior", "Periodo actual"):
        datos = serie.loc[serie["periodo_etiqueta"] == etiqueta]
        if datos.empty:
            continue
        es_actual = etiqueta == "Periodo actual"
        figura.add_trace(go.Scatter(
            x=datos["indice"], y=datos[columna], mode="lines", name=etiqueta,
            line=dict(
                color=colores[etiqueta], width=2 if es_actual else 2,
                dash="solid" if es_actual else "dot",
            ),
            hovertemplate=(
                "Día %{x}<br>" +
                (f"{etiqueta}: $%{{y:,.2f}} MXN" if es_moneda else f"{etiqueta}: %{{y:,.0f}}") +
                "<extra></extra>"
            ),
        ))

    figura.update_xaxes(title="Día del periodo")
    figura.update_yaxes(tickprefix="$" if es_moneda else "", tickformat=",.0f")
    return _titulo(figura, titulo, "Ambos periodos alineados por su día número 1")


def barras_temporales(
    serie: pd.DataFrame, columna: str, titulo: str,
    color: str = COLOR_PEDIDOS, es_moneda: bool = False,
) -> go.Figure:
    """Barras por periodo (pedidos o unidades por día)."""
    if serie.empty or columna not in serie.columns:
        return figura_vacia()

    figura = _figura_base()
    figura.add_trace(go.Bar(
        x=serie["periodo"], y=serie[columna], name=titulo,
        marker=dict(color=color, line=dict(width=0)),
        hovertemplate=(
            "<b>%{x|%d/%m/%Y}</b><br>" +
            (f"{titulo}: $%{{y:,.2f}} MXN" if es_moneda else f"{titulo}: %{{y:,.0f}}") +
            "<extra></extra>"
        ),
    ))
    # 2 px de separación entre barras: se leen como marcas independientes.
    figura.update_layout(bargap=0.25)
    figura.update_yaxes(tickprefix="$" if es_moneda else "", tickformat=",.0f")
    return _titulo(figura, titulo)


def multiserie_temporal(
    serie: pd.DataFrame, columnas: dict[str, tuple[str, str]], titulo: str
) -> go.Figure:
    """Varias métricas de la **misma escala** en una sola gráfica.

    Args:
        columnas: ``{columna: (etiqueta, color)}``.  Todas deben ser importes en
            pesos: mezclar pesos con unidades exigiría un segundo eje, que este
            módulo no usa nunca.
    """
    if serie.empty:
        return figura_vacia()

    figura = _figura_base(mostrar_leyenda=True)
    for columna, (etiqueta, color) in columnas.items():
        if columna not in serie.columns:
            continue
        figura.add_trace(go.Scatter(
            x=serie["periodo"], y=serie[columna], mode="lines", name=etiqueta,
            line=dict(color=color, width=2),
            hovertemplate=f"<b>%{{x|%d/%m/%Y}}</b><br>{etiqueta}: $%{{y:,.2f}} MXN<extra></extra>",
        ))
    figura.update_yaxes(tickprefix="$", tickformat=",.0f")
    return _titulo(figura, titulo)


# =============================================================================
# Composición financiera
# =============================================================================


def cascada_neto(desglose: pd.DataFrame, titulo: str = "De las ventas brutas al neto depositable") -> go.Figure:
    """Gráfica waterfall: cómo se llega del ingreso bruto al depósito."""
    if desglose.empty:
        return figura_vacia()

    medida = {"absoluto": "absolute", "relativo": "relative", "total": "total"}
    figura = _figura_base(alto=440)

    figura.add_trace(go.Waterfall(
        orientation="v",
        measure=[medida.get(t, "relative") for t in desglose["tipo"]],
        x=desglose["concepto"],
        y=desglose["importe"],
        text=[f"${abs(v):,.0f}" for v in desglose["importe"]],
        textposition="outside",
        textfont=dict(size=11, color=COLOR_TINTA_SECUNDARIA),
        connector=dict(line=dict(color=COLOR_EJE, width=1)),
        increasing=dict(marker=dict(color=COLOR_VENTAS)),
        decreasing=dict(marker=dict(color=COLOR_TARIFAS)),
        totals=dict(marker=dict(color=COLOR_NETO)),
        hovertemplate="<b>%{x}</b><br>$%{y:,.2f} MXN<extra></extra>",
    ))
    figura.update_layout(hovermode="closest")
    figura.update_xaxes(tickangle=-25)
    figura.update_yaxes(tickprefix="$", tickformat=",.0f")
    return _titulo(figura, titulo, "Las barras naranjas son lo que descuenta Amazon")


def barras_desglose_tarifas(tarifas: pd.DataFrame) -> go.Figure:
    """Barras horizontales con la composición de los cargos."""
    if tarifas.empty:
        return figura_vacia("No se registraron cargos en el periodo.")

    datos = tarifas.sort_values("importe")
    figura = _figura_base(alto=max(280, 46 * len(datos)))

    figura.add_trace(go.Bar(
        y=datos["concepto"], x=datos["importe"], orientation="h",
        marker=dict(color=COLOR_TARIFAS, line=dict(width=0)),
        text=[f"${v:,.0f} · {p:.1%}" for v, p in zip(datos["importe"], datos["participacion"])],
        textposition="outside",
        textfont=dict(size=11, color=COLOR_TINTA_SECUNDARIA),
        hovertemplate="<b>%{y}</b><br>$%{x:,.2f} MXN<extra></extra>",
        cliponaxis=False,
    ))
    figura.update_layout(hovermode="closest", bargap=0.3)
    figura.update_xaxes(tickprefix="$", tickformat=",.0f", showgrid=True, gridcolor=COLOR_REJILLA)
    figura.update_yaxes(showgrid=False)
    return _titulo(figura, "Composición de los cargos de Amazon")


def dona_composicion(
    datos: pd.DataFrame, columna_etiqueta: str, columna_valor: str,
    titulo: str, subtitulo: str = "",
) -> go.Figure:
    """Distribución porcentual.  Se limita a ocho porciones más «Otros»."""
    if datos.empty:
        return figura_vacia()

    resumido = _agrupar_en_otros(datos, columna_etiqueta, columna_valor)
    figura = _figura_base(alto=380, mostrar_leyenda=True)

    figura.add_trace(go.Pie(
        labels=resumido[columna_etiqueta],
        values=resumido[columna_valor].abs(),
        hole=0.58,
        marker=dict(
            colors=PALETA_CATEGORICA[: len(resumido)],
            line=dict(color=COLOR_SUPERFICIE, width=2),  # separación de 2 px entre porciones
        ),
        textinfo="percent",
        textposition="inside",
        insidetextfont=dict(size=12, color="#ffffff"),
        hovertemplate="<b>%{label}</b><br>$%{value:,.2f} MXN<br>%{percent}<extra></extra>",
        sort=True,
        direction="clockwise",
    ))
    figura.update_layout(hovermode=False)
    return _titulo(figura, titulo, subtitulo)


def comparacion_bruto_neto(metricas: dict) -> go.Figure:
    """Barras que contrastan la venta bruta con lo que realmente se deposita."""
    conceptos = ["Ventas brutas", "Ventas con impuestos", "Neto depositable"]
    valores = [
        metricas.get("ventas_brutas", 0.0),
        metricas.get("ventas_con_impuestos", 0.0),
        metricas.get("neto", 0.0),
    ]
    colores = [COLOR_VENTAS, COLOR_IMPUESTOS, COLOR_NETO]

    figura = _figura_base(alto=340)
    figura.add_trace(go.Bar(
        x=conceptos, y=valores,
        marker=dict(color=colores, line=dict(width=0)),
        text=[f"${v:,.0f}" for v in valores],
        textposition="outside",
        textfont=dict(size=12, color=COLOR_TINTA_SECUNDARIA),
        hovertemplate="<b>%{x}</b><br>$%{y:,.2f} MXN<extra></extra>",
        cliponaxis=False,
    ))
    figura.update_layout(hovermode="closest", bargap=0.45)
    figura.update_yaxes(tickprefix="$", tickformat=",.0f")
    return _titulo(figura, "Ventas frente al neto depositable")


# =============================================================================
# Productos
# =============================================================================


def top_barras(
    tabla: pd.DataFrame,
    columna_etiqueta: str,
    columna_valor: str,
    titulo: str,
    subtitulo: str = "",
    color: str = COLOR_VENTAS,
    es_moneda: bool = True,
    top: int = 10,
) -> go.Figure:
    """Top N en barras horizontales, ordenadas de mayor a menor."""
    if tabla.empty or columna_valor not in tabla.columns:
        return figura_vacia()

    datos = (
        tabla.nlargest(top, columna_valor)
        .sort_values(columna_valor)
        .copy()
    )
    if datos.empty:
        return figura_vacia()

    etiquetas = datos[columna_etiqueta].astype(str).str.slice(0, 42)
    formato = "$%{x:,.2f} MXN" if es_moneda else "%{x:,.0f}"

    figura = _figura_base(alto=max(300, 40 * len(datos)))
    figura.add_trace(go.Bar(
        y=etiquetas, x=datos[columna_valor], orientation="h",
        marker=dict(color=color, line=dict(width=0)),
        text=[
            f"${v:,.0f}" if es_moneda else f"{v:,.0f}"
            for v in datos[columna_valor]
        ],
        textposition="outside",
        textfont=dict(size=11, color=COLOR_TINTA_SECUNDARIA),
        hovertemplate=f"<b>%{{y}}</b><br>{formato}<extra></extra>",
        cliponaxis=False,
    ))
    figura.update_layout(hovermode="closest", bargap=0.28)
    figura.update_xaxes(
        tickprefix="$" if es_moneda else "", tickformat=",.0f",
        showgrid=True, gridcolor=COLOR_REJILLA,
    )
    figura.update_yaxes(showgrid=False)
    return _titulo(figura, titulo, subtitulo)


def pareto(datos: pd.DataFrame, columna_etiqueta: str, top: int = 20) -> go.Figure:
    """Curva de Pareto 80/20 sobre la participación acumulada de ventas.

    Se grafica **solo** la curva acumulada (un eje): las ventas absolutas ya
    tienen su propia gráfica de barras.
    """
    if datos.empty:
        return figura_vacia()

    recorte = datos.head(top)
    figura = _figura_base(alto=360)

    figura.add_trace(go.Scatter(
        x=recorte[columna_etiqueta].astype(str),
        y=recorte["participacion_acumulada"] * 100,
        mode="lines+markers",
        name="Participación acumulada",
        line=dict(color=COLOR_VENTAS, width=2),
        marker=dict(size=8, color=COLOR_VENTAS, line=dict(color=COLOR_SUPERFICIE, width=2)),
        hovertemplate="<b>%{x}</b><br>Acumulado: %{y:.1f}%<extra></extra>",
    ))

    # Referencia del 80 %: la línea que separa el núcleo del catálogo de la cola.
    figura.add_hline(
        y=80, line=dict(color=COLOR_TINTA_TENUE, width=1, dash="dash"),
        annotation_text="80% de las ventas", annotation_position="top left",
        annotation_font=dict(size=11, color=COLOR_TINTA_TENUE),
    )
    figura.update_yaxes(ticksuffix="%", range=[0, 105])
    figura.update_xaxes(tickangle=-45)
    return _titulo(
        figura, "Curva de Pareto por SKU",
        "Cuántos productos concentran la mayor parte de la venta",
    )


def dispersion_sku(tabla: pd.DataFrame) -> go.Figure:
    """Relación entre el volumen vendido y el margen neto de cada SKU.

    En una dispersión los colores deben distinguirse por pares, no solo entre
    vecinos, así que se usa un color único y el tamaño codifica las unidades.
    """
    if tabla.empty:
        return figura_vacia()

    datos = tabla.loc[tabla["ventas"] > 0].copy()
    if datos.empty:
        return figura_vacia()

    figura = _figura_base(alto=420)
    tamanos = datos["unidades"].clip(lower=1)
    figura.add_trace(go.Scatter(
        x=datos["ventas"],
        y=datos["margen_neto"] * 100,
        mode="markers",
        marker=dict(
            size=tamanos,
            sizemode="area",
            sizeref=2.0 * max(tamanos.max(), 1) / (34.0**2),
            sizemin=8,
            color=COLOR_VENTAS,
            opacity=0.75,
            line=dict(color=COLOR_SUPERFICIE, width=2),  # anillo de 2 px al traslaparse
        ),
        customdata=datos[["sku", "unidades"]].values,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>Ventas: $%{x:,.2f} MXN<br>"
            "Margen neto: %{y:.1f}%<br>Unidades: %{customdata[1]:,.0f}<extra></extra>"
        ),
    ))
    figura.update_layout(hovermode="closest")
    figura.update_xaxes(title="Ventas del periodo", tickprefix="$", tickformat=",.0f")
    figura.update_yaxes(title="Margen neto", ticksuffix="%")
    return _titulo(
        figura, "Volumen frente a margen por SKU",
        "El tamaño de cada punto representa las unidades vendidas",
    )


# =============================================================================
# Geografía
# =============================================================================


def mapa_mexico(tabla_estados: pd.DataFrame, columna_valor: str = "ventas") -> go.Figure | None:
    """Mapa coroplético de México por estado.

    Requiere descargar un GeoJSON público.  Si no hay conexión devuelve ``None``
    y la página muestra una gráfica de barras en su lugar.
    """
    geojson = _cargar_geojson_mexico()
    if geojson is None or tabla_estados.empty:
        return None

    figura = go.Figure(go.Choropleth(
        geojson=geojson,
        locations=tabla_estados["estado"],
        z=tabla_estados[columna_valor],
        featureidkey="properties.name",
        colorscale=[[i / (len(RAMPA_SECUENCIAL) - 1), c] for i, c in enumerate(RAMPA_SECUENCIAL)],
        marker=dict(line=dict(color=COLOR_SUPERFICIE, width=1)),
        colorbar=dict(
            title=dict(text="Ventas", font=dict(size=12, color=COLOR_TINTA_TENUE)),
            tickprefix="$", tickformat=",.0f", thickness=14, len=0.75,
            tickfont=dict(size=11, color=COLOR_TINTA_TENUE),
        ),
        hovertemplate="<b>%{location}</b><br>$%{z:,.2f} MXN<extra></extra>",
    ))
    figura.update_geos(
        fitbounds="locations", visible=False, bgcolor=COLOR_SUPERFICIE,
    )
    figura.update_layout(
        height=520,
        paper_bgcolor=COLOR_SUPERFICIE,
        plot_bgcolor=COLOR_SUPERFICIE,
        font=dict(family=FUENTE_UI, size=13, color=COLOR_TINTA_SECUNDARIA),
        margin=dict(l=0, r=0, t=44, b=0),
        title=dict(
            text="Ventas por estado", x=0, xanchor="left",
            font=dict(size=15, color=COLOR_TINTA),
        ),
    )
    return figura


def _cargar_geojson_mexico() -> dict | None:
    """Descarga (y cachea) el GeoJSON de los estados de México."""
    import json
    import urllib.request

    import streamlit as st

    from utils.constants import GEOJSON_MEXICO_URL

    @st.cache_data(ttl=86_400, show_spinner=False)
    def _descargar() -> dict | None:
        try:
            with urllib.request.urlopen(GEOJSON_MEXICO_URL, timeout=12) as respuesta:
                return json.loads(respuesta.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - sin conexión se usa el respaldo en barras
            return None

    return _descargar()


# =============================================================================
# Reembolsos
# =============================================================================


def pedidos_vs_reembolsos(serie: pd.DataFrame) -> go.Figure:
    """Ventas frente a reembolsos por periodo, ambos en pesos (un solo eje)."""
    if serie.empty:
        return figura_vacia()

    figura = _figura_base(mostrar_leyenda=True)
    figura.add_trace(go.Bar(
        x=serie["periodo"], y=serie["ventas"], name="Ventas",
        marker=dict(color=COLOR_VENTAS, line=dict(width=0)),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Ventas: $%{y:,.2f} MXN<extra></extra>",
    ))
    figura.add_trace(go.Bar(
        x=serie["periodo"], y=serie["reembolsos"], name="Reembolsos",
        marker=dict(color=COLOR_REEMBOLSOS, line=dict(width=0)),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Reembolsos: $%{y:,.2f} MXN<extra></extra>",
    ))
    figura.update_layout(barmode="group", bargap=0.28, bargroupgap=0.08)
    figura.update_yaxes(tickprefix="$", tickformat=",.0f")
    return _titulo(figura, "Ventas frente a reembolsos")


def barras_liquidaciones(liquidaciones: pd.DataFrame) -> go.Figure:
    """Neto de cada liquidación.  El signo se distingue por color de estado."""
    if liquidaciones.empty:
        return figura_vacia()

    datos = liquidaciones.copy()
    colores = [COLOR_NETO if v >= 0 else COLOR_CRITICO for v in datos["neto"]]

    figura = _figura_base(alto=max(300, 46 * len(datos)))
    figura.add_trace(go.Bar(
        y=datos["id_liquidacion"].astype(str), x=datos["neto"], orientation="h",
        marker=dict(color=colores, line=dict(width=0)),
        text=[f"${v:,.0f}" for v in datos["neto"]],
        textposition="outside",
        textfont=dict(size=11, color=COLOR_TINTA_SECUNDARIA),
        hovertemplate="<b>Liquidación %{y}</b><br>Neto: $%{x:,.2f} MXN<extra></extra>",
        cliponaxis=False,
    ))
    figura.update_layout(hovermode="closest", bargap=0.3)
    figura.update_xaxes(tickprefix="$", tickformat=",.0f", showgrid=True, gridcolor=COLOR_REJILLA)
    figura.update_yaxes(showgrid=False, title="Id. de liquidación")
    return _titulo(figura, "Neto por liquidación")


def barras_horas(df: pd.DataFrame) -> go.Figure:
    """Distribución de las ventas por hora del día."""
    from utils.constants import COL_HORA, COL_TIPO, COL_VENTAS, TIPO_PEDIDO

    if df.empty or COL_HORA not in df.columns:
        return figura_vacia()

    pedidos = df.loc[df[COL_TIPO].astype("string") == TIPO_PEDIDO]
    if pedidos.empty:
        return figura_vacia()

    por_hora = (
        pedidos.groupby(pedidos[COL_HORA].astype("Int64"), observed=True)[COL_VENTAS]
        .sum()
        .reindex(range(24), fill_value=0.0)
    )

    figura = _figura_base(alto=320)
    figura.add_trace(go.Bar(
        x=[f"{h:02d}:00" for h in por_hora.index], y=por_hora.values,
        marker=dict(color=COLOR_UNIDADES, line=dict(width=0)),
        hovertemplate="<b>%{x}</b><br>Ventas: $%{y:,.2f} MXN<extra></extra>",
    ))
    figura.update_layout(bargap=0.2)
    figura.update_yaxes(tickprefix="$", tickformat=",.0f")
    return _titulo(figura, "Ventas por hora del día", "Hora local del reporte de Amazon")


# =============================================================================
# Utilidades de color
# =============================================================================


def _con_alfa(color_hex: str, alfa: float) -> str:
    """Convierte ``#2a78d6`` en ``rgba(42,120,214,0.1)`` para los rellenos."""
    color = color_hex.lstrip("#")
    r, g, b = (int(color[i: i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alfa})"
