# Waca Market

Aplicaciones distribuidas por Wacatech para su launcher WacaZ.

Los archivos de la tienda están en el release **catalogo**. El launcher lee
`catalog.json` y comprueba si cada APK sigue disponible. Una APK borrada del
release desaparece al abrir de nuevo la tienda con internet, tras actualizar
el catálogo y comprobar el enlace. Borrar la copia original de una PC no retira
la copia publicada. Las apps ya instaladas no se desinstalan al retirarlas.

Para retirar definitivamente una app, quitar también su entrada de catalog.json.
Para reemplazarla, actualizar archivo, versión, tamaño y SHA-256 en el catálogo.
Carátulas extraídas de las APK originales, sin texto promocional añadido.
