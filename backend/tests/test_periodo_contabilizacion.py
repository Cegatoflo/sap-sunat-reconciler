"""
Regresión del bug de "falso Solo SUNAT" por fecha equivocada.

SUNAT arma el Registro de Compras (RCE) por periodo de ANOTACIÓN, no de emisión. En SAP,
esa fecha de anotación es la de contabilización (DocDate). Si se filtra por fecha de emisión
(TaxDate), una factura emitida en un mes y contabilizada en otro (legal: hasta 12 meses para
el crédito fiscal) no calza en el cruce y sale como un falso "Solo SUNAT".

Este test bloquea que alguien vuelva a filtrar por TaxDate sin darse cuenta.
"""
from app.services import sap as sapmod


def test_documentos_compra_filtra_por_fecha_de_contabilizacion():
    # SapSession sin __init__: no toca la red ni necesita .env / settings.
    s = object.__new__(sapmod.SapSession)
    consultas: list[str] = []
    s._todos = lambda path, **kw: consultas.append(path) or []

    s.documentos_compra("2026-06-01", "2026-06-30")

    assert consultas, "documentos_compra no hizo ninguna consulta"
    for path in consultas:
        filtro = path.split("&$filter=")[1]
        # el periodo se acota por DocDate (fecha de contabilización = anotación en el RCE)...
        assert "DocDate ge '2026-06-01'" in filtro
        assert "DocDate le '2026-06-30'" in filtro
        # ...y NO por TaxDate (ese era el bug que marcaba falsos "Solo SUNAT")
        assert "TaxDate ge" not in filtro and "TaxDate le" not in filtro
        # TaxDate se sigue TRAYENDO (en el $select) para mostrar la fecha de emisión
        select = path.split("&$filter=")[0]
        assert "TaxDate" in select
