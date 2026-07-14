#include "ainekio/settings.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    ainekio_servo_bank_t servos;
    ainekio_servo_bank_init(&servos);
    assert(ainekio_servo_bank_calibration_valid(&servos));
    servos.channels[0].calibration.center_degrees = 181.0F;
    assert(!ainekio_servo_bank_calibration_valid(&servos));

    ainekio_pose_bank_t poses;
    ainekio_pose_bank_init(&poses);
    assert(ainekio_pose_bank_valid(&poses));
    const ainekio_servo_target_t targets[] = {{.id = 0U, .degrees = 90.0F},
                                               {.id = 1U, .degrees = 80.0F}};
    assert(ainekio_pose_bank_put(&poses, "neutral", targets, 2U));
    const ainekio_named_pose_t *pose = ainekio_pose_bank_find(&poses, "neutral");
    assert(pose != NULL && pose->count == 2U);
    const ainekio_servo_target_t replacement[] = {{.id = 0U, .degrees = 100.0F}};
    assert(ainekio_pose_bank_put(&poses, "neutral", replacement, 1U));
    pose = ainekio_pose_bank_find(&poses, "neutral");
    assert(pose != NULL && pose->targets[0].degrees == 100.0F);
    const ainekio_servo_target_t duplicate[] = {{.id = 0U, .degrees = 90.0F},
                                                 {.id = 0U, .degrees = 80.0F}};
    assert(!ainekio_pose_bank_put(&poses, "bad", duplicate, 2U));
    assert(ainekio_pose_bank_valid(&poses));
    (void)strcpy(poses.poses[1].name, "neutral");
    poses.poses[1].used = true;
    poses.poses[1].count = 1U;
    poses.poses[1].targets[0] = replacement[0];
    assert(!ainekio_pose_bank_valid(&poses));
    puts("settings tests passed");
    return 0;
}
