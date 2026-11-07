def pytest_configure(config):
    config.addinivalue_line("markers", "slow: runs a real 20 s solve (skip with -m 'not slow')")
