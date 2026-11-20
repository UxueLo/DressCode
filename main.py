from workers.gemini_hilo import ProcesadorPrendas



def main() -> None:

    # --Llamada al procesador de prendas (gemini)
    procesador = ProcesadorPrendas()
    procesador.iniciar()

    try:
        procesador.enviar("04A3B2C1", "data/uploads/camiseta1.jpg")
        procesador.enviar("04A3B2C2", "data/uploads/pantalon1.jpg")

        pendientes = 2
        while pendientes:
            tipo, tag_id, valor = procesador.cola_resultados.get()
            if tipo == "OK":
                print(f"Guardada {tag_id}: {valor.sub_category}")
            else:
                print(f"Error en {tag_id}: {valor}")
            pendientes -= 1

    except KeyboardInterrupt:
        print("\nPrograma interrumpido.")
    finally:
        procesador.cerrar()


if __name__ == "__main__":
    main()