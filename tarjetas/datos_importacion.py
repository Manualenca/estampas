"""Datos revisados por el usuario que el importador aplica a los archivos."""

BAUTISMO = "bautismo"
COMUNION = "comunion"
CONFIRMACION = "confirmacion"

# Oraciones corregidas (original, corregido). La comparación ignora acentos y puntuación.
CORRECCIONES_ORACIONES = [
    (
        "Señor, envíame Tú luz y tú verdad, que ellas sean mi guía.",
        "Señor, envíame tu luz y tu verdad, que ellas sean mi guía.",
    ),
    (
        "Gracias Señor por darme mil razones para confirmar me fe hacia ti",
        "“Gracias, Señor, por darme mil razones para confirmar mi fe hacia ti”.",
    ),
    (
        "Jesús, te doy gracias, porque quisiste quedarte conmigo en la Eucaristía. "
        "Te pido ser generoso con los demás como tu lo eres conmigo.",
        "Jesús, te doy gracias, porque quisiste quedarte conmigo en la Eucaristía. "
        "Te pido ser generoso con los demás como Tú lo eres conmigo.",
    ),
    (
        "Jesús, hoy recibo en mi corazón, quédate conmigo siempre",
        "Jesús, hoy te recibo en mi corazón, quédate conmigo siempre.",
    ),
    (
        "Guárdame, oh Dios, en ti está mi refugio, Tú eres mi bien, nada hay fuera de Tí.",
        "Guárdame, oh Dios, en Ti está mi refugio, Tú eres mi bien, nada hay fuera de Ti.",
    ),
    (
        "Primero fui príncipe de sueños, hoy por tu gracia, soy rey de una realidad. "
        "Te pido Señor, en eta consagración, bendiciones y paz para mi hogar y luz "
        "divina para mi destino.",
        "Primero fui príncipe de sueños, hoy, por tu gracia, soy rey de una realidad. "
        "Te pido, Señor, en esta consagración, bendiciones y paz para mi hogar y luz "
        "divina para mi destino.",
    ),
    (
        "En Dios sólo descansa el alma mía, de El viene mi esperanza, mi salvación, "
        "mi roca sólo es El, mi fortaleza, no he de vacilar.",
        "En Dios sólo descansa el alma mía, de Él viene mi esperanza, mi salvación, "
        "mi roca sólo es Él, mi fortaleza, no he de vacilar.",
    ),
    (
        "Para Dios será sólo mi existencia. Quiero cantar a Dios toda mi vida, y tocar "
        "para El, mientras yo exista.",
        "Para Dios será sólo mi existencia. Quiero cantar a Dios toda mi vida y tocar "
        "para Él mientras yo exista.",
    ),
    (
        "Te doy gracias, Jesús, porque quisiste quedarte conmigo en la Eucaristía. "
        "Quiero caminar seguro que Tú estás a mi lado.",
        "Te doy gracias, Jesús, porque quisiste quedarte conmigo en la Eucaristía. "
        "Quiero caminar seguro de que Tú estás a mi lado.",
    ),
    (
        "Oh Jesús mío, haz que siempre te ame con la inocencia de este día.",
        "¡Oh, Jesús mío!, haz que siempre te ame con la inocencia de este día.",
    ),
    (
        "Me acompaña tu bondad y tu favor mientras dura mi vida, mi misión será la casa "
        "del Señor por largo, largo tiempo.",
        "Me acompañan tu bondad y tu favor mientras dura mi vida, mi misión será la casa "
        "del Señor por largo, largo tiempo.",
    ),
    (
        '¡Jesús mío! en tu hostia pura, pan divino de blancura. Tú eres vida y eres luz. '
        '"Hoy te das al alma mía!" Sé mi encanto, mi alegría y bendíceme, ¡Jesús!',
        '¡Jesús mío!, en tu hostia pura, pan divino de blancura. Tú eres vida y eres luz. '
        '"¡Hoy te das al alma mía!" Sé mi encanto, mi alegría y bendíceme, ¡Jesús!',
    ),
    # Usan "tú" (bendíceme, amarte), no la forma reverencial: "puedes", no "podéis".
    (
        "Señor en este glorioso día en que nada podéis negarme, bendíceme a mí y a toda "
        "mi familia.",
        "Señor, en este glorioso día en que nada puedes negarme, bendíceme a mí y a toda "
        "mi familia.",
    ),
    (
        "Señor, en este día en que nada podéis negarme, bendíceme y bendice a todos los "
        "que me enseñaron a amarte.",
        "Señor, en este día en que nada puedes negarme, bendíceme y bendice a todos los "
        "que me enseñaron a amarte.",
    ),
    ("Señor haz de mí un instrumento de tu paz.", "Señor, haz de mí un instrumento de tu paz."),
    ("Dadme Señor tu Paz y tu Alegría", '"Dadme, Señor, tu paz y tu alegría"'),
    (
        "El Señor es mi pastor nada me puede faltar.",
        "El Señor es mi pastor, nada me puede faltar.",
    ),
    (
        "Que se alegren y regocijen en ti, aquellos que te buscan.",
        "Que se alegren y regocijen en ti aquellos que te buscan.",
    ),
    (
        "Vayan por todo el mundo, anuncien el Evangelio, a toda la creación.",
        "Vayan por todo el mundo, anuncien el Evangelio a toda la creación.",
    ),
    (
        "El corazón que no alberga paz, no entiende a los pobres.",
        "El corazón que no alberga paz no entiende a los pobres.",
    ),
    (
        "Yo soy el pan de vida, el que viene a mí, jamás tendrá hambre.",
        '"Yo soy el pan de vida, el que viene a mí jamás tendrá hambre."',
    ),
    (
        "¡Abre mis ojos, Señor para que vea la luz de tu verdad!",
        "¡Abre mis ojos, Señor, para que vea la luz de tu verdad!",
    ),
    (
        "Jesús, presente en la Eucaristía. Te doy gracias por haberte acercado a mi corazón. "
        "Quiero que me ayudes a ser un hijo bueno, cariñoso, atento, servicial y generoso.",
        "Jesús, presente en la Eucaristía, te doy gracias por haberte acercado a mi corazón. "
        "Quiero que me ayudes a ser un hijo bueno, cariñoso, atento, servicial y generoso.",
    ),
    (
        "Jesús hoy recibo tu amor infinito para que me guíes y acompañes siempre.",
        "Jesús, hoy recibo tu amor infinito para que me guíes y acompañes siempre.",
    ),
    (
        "Jesús en este día, el más hermoso de mi vida, me pongo bajo tu protección junto "
        "a todos aquellos a quienes amo.",
        "Jesús, en este día, el más hermoso de mi vida, me pongo bajo tu protección junto "
        "a todos aquellos a quienes amo.",
    ),
    (
        "Espíritu Santo, con tus siete dones, ilumina mis pasos, lléname de amor y "
        "acompáñame siempre",
        "Espíritu Santo, con tus siete dones, ilumina mis pasos, lléname de amor y "
        "acompáñame siempre.",
    ),
    (
        "¡Bendice al Señor, alma mía! Eres grande, Oh Señor, mi Dios, vestido de honor y "
        "de gloria, envuelto de luz como un manto.",
        "¡Bendice al Señor, alma mía! Eres grande, oh Señor, mi Dios, vestido de honor y "
        "de gloria, envuelto de luz como un manto.",
    ),
    (
        "Señor, Dios de los cielos, ¡Feliz el que en Ti pone su confianza!",
        "Señor, Dios de los cielos, ¡feliz el que en Ti pone su confianza!",
    ),
    (
        "La Luz de Dios se enciende en mi corazón, para iluminar todo el camino de mi vida.",
        "La luz de Dios se enciende en mi corazón para iluminar todo el camino de mi vida.",
    ),
    (
        "“Que este día Sagrado permanezca en mi corazón como un momento de paz y luz.”",
        "“Que este día sagrado permanezca en mi corazón como un momento de paz y luz.”",
    ),
]

CORRECCIONES_CITAS = {
    "(Jesús)": "Jesús",
    "Jn. 6,35": "Jn 6,35",
    "Salmo N° 8": "Salmo 8",
    "Marcos, XVI, 15": "Mc 16,15",
}

# Sacramentos decididos a mano: reemplazan a los del archivo de origen.
SACRAMENTOS_POR_ORACION = [
    (
        "Oh buen Jesús, has venido a mi corazón por primera vez en este día y yo te adoraré "
        "por aquellos que se olvidan de ti.",
        [COMUNION],
    ),
    (
        "Hoy mi alma es un jardín de transparencia donde brillan las flores sin cesar; haz, "
        "Jesús, que florezca mi inocencia cada vez que vuelva a comulgar.",
        [COMUNION],
    ),
    (
        "Dulcísimo Jesús, tú que eres la verdad y la luz, ilumina mi alma por siempre en este "
        "día, dándole la eterna pureza de tu divina bondad, y concede a mi hogar, a mis padres "
        "y a mis seres queridos tu protección y tus bendiciones.",
        [BAUTISMO, COMUNION],
    ),
    (
        "Ven a mí, Jesús querido, y úname a tu corazón; que tú siempre estés conmigo es lo "
        "que más deseo.",
        [BAUTISMO, COMUNION],
    ),
]

# Textos propios de algunos archivos: (clave, sacramento, cantidad de chicos, texto).
_CELEBRADA_LOCALIDAD = "Celebrada en {articulo} {parroquia}\n{localidad}\n{fecha}"
_SOLO_ETIQUETA_PADRINO = [
    ("padrinos_solo_padrino", None, None, "Padrino: {padrino}"),
    ("padrinos_solo_madrina", None, None, "Madrina: {madrina}"),
]
_BAUTISMO_POR_RENGLONES = (
    "Me bautizaron el día\n{fecha}\nEn {articulo} {parroquia}\nMis papis\n{madre} y {padre}\n"
    "Mis Padrinos\n{madrina} y {padrino}"
)
_FECHA_LUGAR_LOCALIDAD = "{fecha}\n{parroquia}\n{localidad}"

PLANTILLAS_POR_ARCHIVO = {
    "Tarj2003": [
        ("celebracion", None, None, "Celebrada en {articulo} {parroquia}\nel {fecha}.\n{localidad}")
    ],
    "Tarj2052_Bautismo": [
        ("titulo_sin_recuerdo", BAUTISMO, None, "{Posesivo} Bautismo y Primera Comunión"),
        ("titulo_sin_recuerdo", CONFIRMACION, None, "{Posesivo} Confirmación"),
        (
            "celebracion",
            BAUTISMO,
            None,
            "Me bautizaron y recibí la\nSanta Eucaristía el\n{fecha} a las {hora} hs.",
        ),
        (
            "celebracion",
            CONFIRMACION,
            None,
            "Recibí el Sacramento de la Confirmación\nel {fecha} a las {hora} hs.",
        ),
        ("celebracion", None, None, "{parroquia}.\n{localidad}\n{anio}"),
    ],
    "Tarj2055": [("celebracion", None, None, _FECHA_LUGAR_LOCALIDAD)],
    "Tarj2055_1": [("celebracion", None, None, _FECHA_LUGAR_LOCALIDAD)],
    "Tarj2055_11": _SOLO_ETIQUETA_PADRINO,
    "Tarj2057_1": [
        ("celebracion", None, None, "Celebrada en {articulo} {parroquia}\nel {fecha}\n{localidad}")
    ],
    "Tarj2058": [
        (
            "celebracion",
            CONFIRMACION,
            None,
            "{linea_padrinos}\nCelebrado en {articulo} {parroquia}\nEl {fecha}\n{localidad}",
        ),
        *_SOLO_ETIQUETA_PADRINO,
    ],
    "Tarj2061": [
        ("celebracion", COMUNION, 1, "El {fecha}\nrecibo {posesivo} {sacramentos}\nen {articulo} {parroquia}.")
    ],
    "Tarj2076": [("celebracion", None, None, "Celebrada en {articulo} {parroquia}.\n{localidad}")],
    "Tarj2076_1": [("celebracion", None, None, "Celebrada en {articulo} {parroquia}.\n{localidad}")],
    "Tarj2083": [
        ("padrinos_solo_madrina", None, None, "Me acompaña en este día mi Madrina {madrina}"),
        ("padrinos_solo_padrino", None, None, "Me acompaña en este día mi Padrino {padrino}"),
    ],
    "Tarj2085": [("celebracion", None, None, "{parroquia}\n{fecha}\n{localidad}")],
    "Tarj2094": [
        ("celebracion", None, None, "Celebrada en {articulo} {parroquia}\n{localidad}\nEl {fecha}")
    ],
    "Tarj2130": [("celebracion", None, None, _CELEBRADA_LOCALIDAD)],
    "Tarj3004_sin_oracion": [("celebracion", BAUTISMO, None, _BAUTISMO_POR_RENGLONES)],
    "Tarj3021": [
        ("celebracion", BAUTISMO, None, "{linea_padres}\n{linea_padrinos}\n{fecha}\n{parroquia}")
    ],
    "Tarj3076": [("celebracion", BAUTISMO, None, _BAUTISMO_POR_RENGLONES)],
    "Tarj3079": [
        (
            "celebracion",
            BAUTISMO,
            None,
            "¡Señor, bendíceme hoy y siempre!\n{localidad}\n{fecha}\n{parroquia}\n"
            "{linea_padres}\n{linea_padrinos}",
        )
    ],
    "Tarj3087": [
        ("titulo_completo", None, None, "Invitación a {Posesivo} {sacramentos}"),
        (
            "celebracion",
            None,
            None,
            "Junto con Mi Papis, {madre} y {padre}, te invitamos a acompañarnos a la Ceremonia "
            "religiosa el {fecha} a hs. {hora} en {articulo} {parroquia}.",
        ),
    ],
}
