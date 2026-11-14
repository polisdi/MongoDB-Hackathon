import time
from agent import run_invoice
t = time.time()
print(run_invoice("client_a", "inv_a_001", mode="ablated"))
print(f"{time.time() - t:.1f}s")

