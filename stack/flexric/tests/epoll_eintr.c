/* Test the actual FlexRIC ASIO function against a real interrupted kernel wait. */
#include "asio_xapp.h"
#include <assert.h>
#include <signal.h>
#include <stdio.h>
#include <sys/wait.h>
#include <unistd.h>

static volatile sig_atomic_t interrupted;
static void alarm_handler(int signo) { (void)signo; interrupted=1; }

int main(void) {
  struct sigaction sa={0};
  sa.sa_handler=alarm_handler;
  sigemptyset(&sa.sa_mask);
  assert(sigaction(SIGALRM,&sa,NULL)==0); /* deliberately no SA_RESTART */
  asio_xapp_t io;
  init_asio_xapp(&io);
  int timer=create_timer_ms_asio_xapp(&io,100,100);
  ualarm(10000,0);
  assert(event_asio_xapp(&io)==timer);
  assert(interrupted==1);
  rm_fd_asio_xapp(&io,timer);
  close(io.efd);

  /* Do not turn a genuinely invalid descriptor into an endless retry. */
  pid_t pid=fork();
  assert(pid>=0);
  if(pid==0) {
    io.efd=-1;
    (void)event_asio_xapp(&io);
    _exit(99);
  }
  int status;
  assert(waitpid(pid,&status,0)==pid);
  assert(WIFSIGNALED(status) && WTERMSIG(status)==SIGABRT);
  puts("PASS: interrupted wait resumes; genuine descriptor failure remains fatal");
  return 0;
}
