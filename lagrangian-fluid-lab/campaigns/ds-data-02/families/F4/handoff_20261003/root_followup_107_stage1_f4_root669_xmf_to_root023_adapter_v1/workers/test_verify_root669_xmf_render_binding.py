#!/usr/bin/env python3
from verify_root669_xmf_render_binding import synthetic_tests
if __name__=='__main__':
    checks=synthetic_tests(); assert len(checks)==5
    print('fresh107 synthetic tests: PASS ('+'; '.join(checks)+')')
