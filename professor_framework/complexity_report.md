Below is the time‐complexity analysis for each function. Each block shows only the function’s code (no existing comments) with new annotations for per‐line costs and a final total complexity.

```py 
def mod_exp(x: int, y: int, N: int) -> int:
    # Let b = bit‐length of y, n = bit‐length of N
    if y == 0:
        return 1  # O(1)
    z = mod_exp(x, y // 2, N)
    # recursive call depth: Θ(b)
    # each step does one or two modular multiplications
    
    if y % 2 == 0:
        return (z * z) % N
        # modular multiplication cost M(n)=Θ(n^2)
        # modular reduction also Θ(n^2)
    else:
        return (x * z * z) % N
        # two multiplications + one reduction: still Θ(n^2)

# Total: T(b,n)=T(b−1,n)+Θ(n^2) ⇒ Θ(b·n^2)
# If b≈n, then Θ(n^3)
```

```py
def fermat(N: int, k: int) -> bool:
    # n = bit‐length of N
    for _ in range(k):
        a = random.randint(1, N - 1)  # O(1)
        if mod_exp(a, N - 1, N) != 1:
            return False
        # mod_exp cost: Θ(n^2·b) with b≈n ⇒ Θ(n^3)
    return True

# Total: Θ(k · n^3)
```

```py
def miller_rabin(N: int, k: int) -> bool:
    # n = bit‐length of N

    def single_test(N: int, a: int) -> bool:
        d = N - 1

        # divide out factors of 2
        while not d & 1:
            d >>= 1  # bit‐shift O(1)
        # loop runs Θ(b) times with b≈n ⇒ Θ(n)

        if mod_exp(a, d, N) == 1:
            return True
        # cost: Θ(n^3)

        # repeatedly square until d reaches N−1
        while d < N - 1:
            if mod_exp(a, d, N) == N - 1:
                return True
            d <<= 1  # O(1)
        # loop runs Θ(n) iterations; each mod_exp Θ(n^3)
        # ⇒ Θ(n · n^3)=Θ(n^4)

        return False

    for _ in range(k):
        a = random.randint(2, N - 1)  # O(1)
        if not single_test(N, a):
            return False
    return True

# single_test: Θ(n^4)
# Total: Θ(k · n^4)
```

```py
def generate_large_prime(bits: int) -> int:
    # bits = desired prime size
    while True:
        p = random.getrandbits(bits) | 1  # O(bits)=O(n)
        if miller_rabin(p, 20):
            return p
        # each MR test: Θ(k·n^4), k=20 constant
        # expected trials ≈O(n) ⇒ O(n·n^4)=Θ(n^5)
```

```py
def main(n_bits: int):
    start = time()         # O(1)
    large_prime = generate_large_prime(n_bits)
    print(large_prime)     # O(n_bits)
    print(f'Generation took {time() - start} seconds')  # O(1)

# Total dominated by generate_large_prime: Θ(n^5)
```

# Summary:

- mod_exp: Θ(b·n²) → Θ(n³) if exponent size ≈ modulus size
- fermat: Θ(k·n³)
- miller_rabin: Θ(k·n⁴)
- generate_large_prime: Θ(n·n⁴)=Θ(n⁵)
- main: Θ(n⁵) dominated by prime generation