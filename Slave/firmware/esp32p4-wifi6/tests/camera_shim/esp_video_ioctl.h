#pragma once
#include <time.h>
#include <linux/videodev2.h>
#define VIDIOC_S_DQBUF_TIMEOUT _IOW('V', 200, struct timeval)
