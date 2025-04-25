import os
import json
import asyncio
import httpx
import requests
from bs4 import BeautifulSoup
import certifi

# --- CONFIGURACIÓN ---
WISPHUB_API_KEY = "8y9shUSt.0QurQCnj7ozidVw5jAK2js7brQ2j4jY3"
# -----------------------

async def buscar_cliente(cedula=None, referencia=None):
    """
    Consulta WispHub para buscar un cliente por DNI/C.I./C.C.
    Devuelve dict con id_servicio, nombre y cedula, o None.
    """
    url = "https://api.wisphub.app/api/clientes/"
    headers = {
        "Authorization": f"Api-Key {WISPHUB_API_KEY}",
        "Content-Type": "application/json"
    }
    params = {}
    if cedula:
        params["cedula"] = cedula
    elif referencia:
        params["cedula__contains"] = referencia

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers, params=params)
        print("buscar_cliente - Status Code:", r.status_code)
        print("buscar_cliente - Response Text:", r.text)
        if r.status_code == 200:
            data = r.json()
            if data.get("count", 0) > 0:
                c = data["results"][0]
                return {
                    "id_servicio": c.get("id_servicio"),
                    "nombre": " ".join(filter(None, [c.get("nombre"), c.get("apellidos")])),
                    "cedula": c.get("cedula")
                }
            else:
                print("buscar_cliente: No se encontró cliente con cedula/referencia")
        else:
            print("buscar_cliente: Error, status code:", r.status_code)
    except Exception as e:
        print("buscar_cliente: Excepción", e)
    return None

async def obtener_saldo(id_servicio: int):
    """
    Obtiene y suma todas las facturas pendientes (en USD) para un servicio.
    Devuelve dict con:
      - monto_factura_usd: suma en USD de todas las facturas pendientes
      - saldo_total_bs: esa suma convertida a bolívares según la tasa BCV
      - facturas: lista completa de facturas
    """
    url = f"https://api.wisphub.app/api/clientes/{id_servicio}/saldo/"
    headers = {
        "Authorization": f"Api-Key {WISPHUB_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
        print("obtener_saldo - Status Code:", r.status_code)
        print("obtener_saldo - Response Text:", r.text)
        if r.status_code != 200:
            return None

        data = r.json()
        facturas = data.get("facturas", [])

        # Suma de todas las facturas en USD
        monto_factura_usd = sum(
            float(f.get("total", 0.0)) for f in facturas
        )

        # Convertimos a bolívares usando la tasa en tiempo real
        tasa = await consultar_tasa_bcv()
        saldo_total_bs = round(monto_factura_usd * tasa, 2)

        return {
            "monto_factura_usd": monto_factura_usd,
            "saldo_total_bs": saldo_total_bs,
            "facturas": facturas
        }
    except Exception as e:
        print("obtener_saldo: Excepción", e)
        return None

async def consultar_tasa_bcv():
    """
    Intenta primero obtener la tasa por API externa y, si falla, hace scraping del BCV.
    Retorna float.
    """
    url1 = "https://pydolarvenezuela-api.vercel.app/api/v1/dollar?page=bcv"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url1)
        if r.status_code == 200 and r.text.strip():
            data = r.json()
            tasa = data.get("moneda", {}).get("precio")
            if tasa:
                print("Tasa obtenida de fuente 1:", tasa)
                return float(tasa)
    except Exception as e:
        print("consultar_tasa_bcv - Error en fuente primaria:", e)

    print("consultar_tasa_bcv - Intentando scraping BCV...")
    tasa_scraped = await asyncio.to_thread(obtener_tasa_bcv)
    if tasa_scraped is not None:
        print("Tasa obtenida del BCV oficial:", tasa_scraped)
        return tasa_scraped

    print("consultar_tasa_bcv - Usando valor por defecto 36.5")
    return 36.5

def obtener_tasa_bcv():
    """
    Hace scraping en https://www.bcv.org.ve/ para extraer la tasa oficial.
    """
    url = "https://www.bcv.org.ve/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # verify=False para evitar errores SSL locales
        r = requests.get(url, headers=headers, timeout=10, verify=False)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            div = soup.find("div", id="dolar")
            if div:
                strong = div.find("strong")
                if strong:
                    text = strong.get_text(strip=True).replace(",", ".")
                    try:
                        return float(text)
                    except ValueError as ve:
                        print("obtener_tasa_bcv - Error conversión:", ve)
                else:
                    print("obtener_tasa_bcv - No encontré <strong> en div#dolar")
            else:
                print("obtener_tasa_bcv - No encontré div#dolar")
        else:
            print("obtener_tasa_bcv - HTTP status:", r.status_code)
    except Exception as e:
        print("obtener_tasa_bcv - Excepción:", e)
    return None

async def registrar_pago(data):
    """
    Registra un pago en WispHub:
      1) Convierte Bs a USD
      2) Obtiene id_servicio del cliente
      3) Obtiene saldo y factura pendiente
      4) Llama a /facturas/{id_factura}/registrar-pago/
    """
    monto_bs   = data.get("monto")
    referencia = data.get("referenciaBancoOrdenante")
    id_cliente = data.get("idCliente")
    if not (monto_bs and referencia and id_cliente):
        return {"error": "Datos incompletos para registrar el pago"}

    # 1) Convertir a USD
    tasa = await consultar_tasa_bcv()
    try:
        monto_usd = float(monto_bs) / tasa
    except Exception as e:
        return {"error": f"Error conversión monto: {e}"}

    # 2) Buscar cliente para obtener id_servicio
    cli = await buscar_cliente(cedula=id_cliente)
    if not cli:
        return {"error": "Cliente no encontrado en WispHub"}
    id_serv = cli["id_servicio"]

    # 3) Obtener factura pendiente
    saldo_info = await obtener_saldo(id_serv)
    if not saldo_info:
        return {"error": "No pude obtener saldo del cliente"}
    # Tomamos la primera factura de la lista
    factura = (saldo_info.get("facturas") or [None])[0]
    if not factura:
        return {"error": "No hay factura pendiente para registrar pago"}
    id_factura = factura.get("id") or factura.get("id_factura")
    if not id_factura:
        return {"error": "No se pudo determinar el ID de la factura"}

    # 4) Registrar pago en WispHub
    url = f"https://api.wisphub.app/api/facturas/{id_factura}/registrar-pago/"
    headers = {
        "Authorization": f"Api-Key {WISPHUB_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "referencia":    referencia,
        "fecha_pago":    "2025-04-11 12:00",  # puedes usar datetime.now()
        "total_cobrado": monto_usd,
        "accion":        1,
        "forma_pago":    0
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=payload)
        print("registrar_pago - Status:", r.status_code, "Response:", r.text)
        if r.status_code in (200, 201):
            return r.json()
        return {
            "error":   "No se pudo registrar el pago en WispHub",
            "status":  r.status_code,
            "detail":  r.text
        }
    except Exception as e:
        print("registrar_pago - Excepción:", e)
        return {"error": f"Exception al registrar pago: {e}"}

# --- Para pruebas locales ---
if __name__ == "__main__":
    print("Tasa BCV (scraping):", obtener_tasa_bcv())
    async def _test():
        print("Buscar cliente:", await buscar_cliente(cedula="19222296"))
        print("Saldo cliente:", await obtener_saldo(281))
        print("Tasa BCV:", await consultar_tasa_bcv())
    asyncio.run(_test())
