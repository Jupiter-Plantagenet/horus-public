
#include "sync_ui.h"
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>
#include <time.h>
#define CHECK(x) do{if(!(x)) _exit(90);}while(0)
static double now(void) {struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static void *later(void *s) {usleep(20000);signal_sync_ui(s);return NULL;}
int main(void) {
 sync_ui_t s;init_sync_ui(&s);
 for(int i=0;i<8;i++) {prepare_sync_ui(&s);CHECK(!s.flag_sync && !s.msg_ack);signal_sync_ui(&s);double t=now();cond_wait_sync_ui(&s,1000);CHECK(now()-t<0.5 && s.msg_ack);}
 prepare_sync_ui(&s);CHECK(!s.flag_sync && !s.msg_ack);pthread_t th;CHECK(!pthread_create(&th,NULL,later,&s));cond_wait_sync_ui(&s,1000);CHECK(!pthread_join(th,NULL));CHECK(s.msg_ack);
 for(int rejected=0;rejected<2;rejected++) {
  pid_t pid=fork();CHECK(pid>=0);
  if(pid==0) {prepare_sync_ui(&s);if(rejected)signal_failure_sync_ui(&s);cond_wait_sync_ui(&s,1);_exit(0);}
  int status;CHECK(waitpid(pid,&status,0)==pid);CHECK(WIFEXITED(status) && WEXITSTATUS(status)==EXIT_FAILURE);
 }
 free_sync_ui(&s);return 0;
}
