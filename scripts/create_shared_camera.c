/* Create one additional loopback; never unload or replace existing devices.
 * Compile against the installed v4l2loopback module's matching header. */
#include <errno.h>
#include <fcntl.h>
#include <linux/types.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include "v4l2loopback.h"

int main(int argc, char **argv) {
    if (argc < 2 || argc > 3) { fprintf(stderr,"Usage: %s VIDEO_NUMBER [LABEL]\n",argv[0]); return 2; }
    char *end;
    long number=strtol(argv[1],&end,10);
    if (end==argv[1] || *end || number<0 || number>255) return 2;
    const char *label=argc==3?argv[2]:"Hyprchan Shared Camera";
    if (!*label || strlen(label)>=32) return 2;
    struct v4l2_loopback_config config={0};
    config.output_nr=(int)number;
    int fd=open("/dev/v4l2loopback",O_RDWR|O_CLOEXEC);
    if (fd<0) { perror("Open loopback control");return 1; }
    if (ioctl(fd,V4L2LOOPBACK_CTL_QUERY,&config)>=0) {
        close(fd);
        if (strncmp(config.card_label,label,sizeof(config.card_label))) {
            fprintf(stderr,"Video number is already used by another loopback\n");return 1;
        }
        return 0;
    }
    memset(&config,0,sizeof(config));
    config.output_nr=(int)number;
    snprintf(config.card_label,sizeof(config.card_label),"%s",label);
    config.min_width=16;config.max_width=1920;
    config.min_height=16;config.max_height=1440;
    config.max_buffers=4;config.max_openers=16;
    /* Capture stays discoverable while the demand-driven feeder is idle. */
    config.announce_all_caps=1;
    int result=ioctl(fd,V4L2LOOPBACK_CTL_ADD,&config);
    if (result<0) perror("Create shared camera");
    close(fd);
    return result<0?1:0;
}
