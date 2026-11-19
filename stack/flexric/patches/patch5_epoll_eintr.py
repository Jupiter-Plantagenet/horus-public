"""Retry an interrupted xApp epoll wait; preserve failures for other errors."""
from pathlib import Path
import sys

def apply(root):
    path=Path(root)/'src/xApp/asio_xapp.c'
    text=path.read_text()
    marker='HORUS: SIGCONT/signal interruption is not an epoll failure'
    if marker in text:return False
    old='  const int events_ready = epoll_wait(io->efd, events, maxevents, timeout_ms);'
    if text.count(old)!=1:raise ValueError('Pinned FlexRIC epoll wait did not match; refusing an unreviewed patch')
    replacement='''  // HORUS: SIGCONT/signal interruption is not an epoll failure.
  int events_ready;
  do {
    events_ready = epoll_wait(io->efd, events, maxevents, timeout_ms);
  } while (events_ready == -1 && errno == EINTR);'''
    path.write_text(text.replace(old,replacement))
    return True

if __name__=='__main__':
    apply(sys.argv[1] if len(sys.argv)>1 else '/opt/flexric')
    print('HORUS: xApp epoll EINTR retry installed; other error assertions retained')
