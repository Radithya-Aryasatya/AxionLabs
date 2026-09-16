import sys
path = sys.argv[1]
a = int(sys.argv[2]); b = int(sys.argv[3])
L = open(path, encoding='utf-8').read().splitlines()
out = "\n".join('%4d| %s' % (i + 1, l) for i, l in enumerate(L[a - 1:b], start=a - 1))
open('_tmpdump_out.txt', 'w', encoding='utf-8').write(out)
print("written", len(L))