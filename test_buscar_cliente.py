import asyncio
from app.utils import buscar_cliente

async def test():
    # Usa un valor que esperes que exista en WispHub.
    cliente = await buscar_cliente(cedula="25931073")
    print("Resultado de buscar_cliente:", cliente)

if __name__ == "__main__":
    asyncio.run(test())
