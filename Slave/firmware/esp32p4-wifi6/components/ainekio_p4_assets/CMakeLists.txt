idf_component_register(SRCS "assets.c" INCLUDE_DIRS "include"
    REQUIRES core esp_common PRIV_REQUIRES joltwallet__littlefs json esp_partition)
