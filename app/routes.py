from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from app.utils import (
    buscar_cliente,
    consultar_tasa_bcv,
    obtener_saldo,
    registrar_pago
)

router = APIRouter()

@router.post("/webhook")
async def recibir_pago(request: Request):
    api_key = request.headers.get("API-KEY")
    if api_key != "TU_API_KEY_BDV":
        return JSONResponse(status_code=403, content={"error": "API KEY inválida"})

    try:
        data = await request.json()
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": "Formato JSON inválido", "detail": str(e)})

    resultado = await registrar_pago(data)
    return JSONResponse(content=resultado)


@router.get("/consulta")
async def consulta_cliente(
    cedula: str = Query(None),
    referencia: str = Query(None)
):
    # 1) Buscamos al cliente y obtenemos el id_servicio
    cliente = await buscar_cliente(cedula=cedula, referencia=referencia)
    if not cliente:
        return JSONResponse(status_code=404, content={"error": "Cliente no encontrado"})

    # 2) Obtenemos el saldo/facturas pendientes
    saldo_info = await obtener_saldo(cliente["id_servicio"])
    if not saldo_info:
        return JSONResponse(status_code=500, content={"error": "No se pudo obtener el saldo del cliente"})

    # 3) Extraemos la tasa (ya usada internamente en obtener_saldo, pero la repetimos aquí para exponerla)
    tasa = await consultar_tasa_bcv()

    return {
        "cliente":            cliente["nombre"],
        "cedula":             cliente["cedula"],
        "id_servicio":        cliente["id_servicio"],
        "tasa_bcv":           tasa,
        "monto_factura_usd":  saldo_info["monto_factura_usd"],
        "saldo_total_bs":     saldo_info["saldo_total_bs"]
    }
