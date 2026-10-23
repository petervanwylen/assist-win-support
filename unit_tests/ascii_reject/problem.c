#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "assist_platform.h"
#include <fcntl.h>
#include "assist.h"
#include "spk.h"

int main(){
    // Scratch file in the current directory rather than mkstemp("/tmp/..."),
    // which is POSIX-only. The other detection tests already work this way.
    const char* tmp = "test_ascii_source.txt";
    int tfd = open(tmp, O_CREAT | O_RDWR | O_TRUNC | O_BINARY, 0644);
    if (tfd<0){
        perror("open");
        return 1;
    }
    const char* content = "JPL EPHEMERIS ASCII SOURCE\n...\n";
    write(tfd, content, strlen(content));
    lseek(tfd, 0, SEEK_SET);

    ephemeris_file_format_t f = assist_detect_ephemeris_file_format(tfd);
    if (f != FILE_FORMAT_UNKNOWN){
        fprintf(stderr, "Expected UNKNOWN (ASCII source unsupported), got %d\n", (int)f);
        close(tfd);
        remove(tmp);
        return 1;
    }
    close(tfd);

    // SPK init should reject
    struct spk_s* sp = assist_spk_init(tmp);
    remove(tmp);
    if (sp != NULL){
        fprintf(stderr, "assist_spk_init unexpectedly succeeded on ASCII file\n");
        assist_spk_free(sp);
        return 1;
    }

    printf("ascii_reject: OK\n");
    return 0;
}



