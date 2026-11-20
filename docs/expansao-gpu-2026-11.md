# Expansao GPU 08/11/2026 — Ternary-Flint-40B e PXA-Fusion4-35B na Tesla P40

Duas famillas novas no `gpu-slot-1`, ambas com pesos em **/dev/sdb1**
(`/mnt/arquivos/models/…`, ext4, `ia move`-compativel) e symlink em
`~/models/<nome>`, ambas no allowlist do `pcsala models switch` e do gestor `ia`.

| | Ternary-Flint-40B | PXA-Fusion4-35B |
|---|---|---|
| unit / porta | `flint-ternary.service` / **8101** | `fusion4.service` / **8102** |
| id pcsala | `flint-ternary-40b` | `fusion4-35b` |
| alias `ia` | `flint-ternary` | `fusion4` |
| perfil | `flint-ternary-v1` (STRATA activo) | `fusion4-agentic-v1` |
| engine | fork **PrismML** `prism` @ 6447906bf | **PXA** v4.0 @ 0a369a5 |
| build | `/home/igor/opt/prism-flint/build` | `/home/igor/opt/pxa/build` |
| CMake | `-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=61` | idem |
| quant | **`PQ2_0` 10,97 GiB** (escolhido por medicao) · `PTQ1_0` 9,31 GiB fica como fallback | `PXQ4` 17,97 GiB |
| ctx da unit | 100 000 | 32 768 (ver §4.4) |

## 1. Porque sao duas engines e nao uma

A tabela de partida pedia "a engine PXA" para os dois. So que os dois
GGUF usam tipos de quant privativos de forks diferentes, registados em ids
GGML **distintos e mutuamente exclusivos**:

| ficheiro | tipos de tensor (medido no cabecalho GGUF) | quem os regista |
|---|---|---|
| `Ternary-Flint-40B-PTQ1_0-Calibrated-9GB.gguf` | 141 × id **143** (`ptq1_0`), 344 × q8_0, 293 × f32, 1 × f16 | fork PrismML (CUDA sm_61 com MMQ/MMVQ) |
| `Ternary-Flint-40B-PQ2_0-Calibrated-11GB.gguf` | id **142** (`pq2_0`) | fork PrismML |
| `PXA-Fusion4-35B-PXQ4.gguf` | 120 × id **252** (`pxq4`), 300 × mxfp4, 308 × f32, 23 × q5_0, 2 × f16 | engine PXA |

O `ggml/include/ggml.h` do PXA traz esses ids queimados e desregistados:

```c
// depricated: GGML_TYPE_IQ2_TN  = 142,
// depricated: GGML_TYPE_IQ1_TN  = 143,
// RETIRADO 2026-08-21 … os ids estao queimados — um GGUF que carregue um
// deles agora apanha a mesma recusa limpa "unregistered type id" no load.
```

Confirmado a executar (build PXA de 08/11, `-ngl 0`):

```text
gguf_init_from_file: tensor 'blk.10.ffn_down_exps.weight' has unregistered type id 143 — unsupported file
llama_model_load: error loading model: … Ternary-Flint-40B-PTQ1_0-Calibrated-9GB.gguf
```

Nao e o PXA que esta velho — e o contrario: o PXA e de 2026-11-07 (v4.0.4,
commit 0a369a5) e suporta `flint`, o P40 (sm_61) e o codec PXQ. Simplesmente
o `PTQ1_0`/`PQ2_0` do Ternary-Flint e um formato **privativo do fork PrismML**,
cujo numero de tipo o PXA reservou para os seus proprios quants. O caminho
cruzado tambem nao existe: o PrismML nao regista o id 252, portanto o
Fusion4 PXQ4 so pega no PXA.

## 2. Patch necessario no PrismML (flint + hadamard)

O ficheiro traz `prism.hadamard.version=1`, `block_size=512`,
`sign_mode=explicit` e `weight_names = blk.N.ffn_{gate,up,down}_exps.weight`
(Os 49 blocos). O loader do fork recusa arquitecturas fora da whitelist de
Hadarmard:

```text
prism.hadamard: arch '%s' is not verified to apply the activation transform to all folded weights
```

O `branch prism` (6447906bf) ja tem a arquitectura `flint`
(`src/models/flint.cpp`, `LLM_ARCH_FLINT`) e os kernels CUDA de `PTQ1_0`/`PQ2_0`
(`mmq-ptq1_0.cuh`, `mmvq-ptq1_0.cuh`, `mmq-pq2_0.cuh`, `hadamard.cu`), mas nao
tinha `flint` na whitelist. Patch de uma linha, em
`deploy/engines/prism-flint-hadamard-whitelist.patch`:

```diff
             case LLM_ARCH_GEMMA4:
+            case LLM_ARCH_FLINT:  // flint: hadamard block 512 nos ffn_*_exps (build_lora_mm_id)
                 break;
```

Requisito verificado: os nomes de tensores declarados no GGUF estao todos no
conjunto `is_foldable_weight` e o caminho MoE de `models/flint.cpp` passa por
`build_lora_mm_id`, que e onde a transformacao se aplica. A whitelist e a
unica porta de entrada; sem ela o arranque aborta com o erro acima.

Aplicacao:

```bash
cd /home/igor/opt && git -C prism-cpu-install-aswyUW/source worktree add --detach \
    /home/igor/opt/prism-flint origin/prism
cd /home/igor/opt/prism-flint && git apply deploy/engines/prism-flint-hadamard-whitelist.patch
cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=61 \
    -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF
cmake --build build --target llama-server llama-cli llama-bench -j6
```

## 3. Patch necessario no PXA (build em Linux/GCC 13)

`GGML_NATIVE` nao e a causa; o que rebenta e o `qsa-topk.cu` — o unico `.cu`
da arvore que inclui `ggml-impl.h`, que por sua vez puxa `<immintrin.h>`
quando `__AVX__`/`__AVX2__` estao definidos. Em GCC 13 o `immintrin.h` inclui
`amxtileintrin.h` incondicionalmente e o `nvcc` (CUDA 12.4) nao conhece os
builtins AMX:

```text
/usr/lib/gcc/x86_64-linux-gnu/13/include/amxtileintrin.h(42): error:
    identifier "__builtin_ia32_ldtilecfg" is undefined
```

Guarda de uma linha em `ggml/src/ggml-impl.h` (o CUDA host nao usa intrinsics
x86 nestes TUs), em `deploy/engines/pxa-cuda-immintrin-guard.patch`:

```diff
-#if defined(__AVX__) || defined(__AVX2__) || … || defined(__SSE__)
+#if (defined(__AVX__) || defined(__AVX2__) || … || defined(__SSE__)) && !defined(__CUDACC__)
 #if !defined(__riscv)
 #include <immintrin.h>
```

Build:

```bash
git clone --depth 1 https://github.com/poisonxa16/pxa /home/igor/opt/pxa
cd /home/igor/opt/pxa
cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=61 \
    -DGGML_SCHED_MAX_COPIES=2 -DPXA_PXQN_CLOSED_SRC=OFF -DPXA_PXQ_ENCODER=OFF \
    -DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON
cmake --build build --target llama-server llama-cli llama-bench llama-quantize -j10
```

Source build = PXQ classico (o Fusion4 e PXQ4 classico) + quants standard; o
PXQN exige a lib fechada e nao esta neste build. O PXA etique o P40 como
`topology="single 1080Ti (sm_61)"` e escolhe `-ub 2048`
(`pxa-registry.cpp:537`, "1x P40-class 24 GB (sm_61) … not measured on a P40
here") — as medicoes abaixo sao a primeira medicao desta celula.

## 4. Medicoes — Tesla P40 (sm_61, 23 040 MiB, CUDA 12.4, driver 580.116.03)

`scripts/bench_gpu_slot.py`, modos `tarefas` / `escala` / `ferramentas` /
`agulha`. JSON cru em `~/bench-results/2026-11-08-gpu-expansion/`.
Os prompts de escala sao numerados e com uuid por execucao: com texto
repetido o cache de prompt do servidor come o prefixo comum e o prefill sai
falso (isto apanhou-se logo na primeira serie e distorcia os números em 2-8×).

### 4.1 Ternary-Flint-40B `PTQ1_0` — `-c 100000 -fa on -ctk/ctv q8_0 -b 512 -ub 256`

VRAM: **11 149 MiB** usadas (pesos 9 535 MiB + KV/buffers ~1 614 MiB), folga ~11 900 MiB.

| contexto | prefill tok/s | decode tok/s | truncado |
|---|---|---|---|
| 4 095 | 240,1 | 46,7 | nao |
| 8 190 | 232,5 | 44,8 | nao |
| 16 354 | 221,8 | 41,5 | nao |
| 32 742 | 204,7 | 35,7 | nao |
| 65 535 | 175,6 | 26,3 | nao |
| **99 048** | **155,0** | **15,7** | nao |

Tarefas (prompt curto, 512 tok): decode **50,7 tok/s** nas 5; prefill 144-168 tok/s.
Tool calling `--jinja`: **3/3** `finish_reason=tool_calls` com `{"comando": "cd /srv/app && git status"}`.
Agulha: **99 582 tokens** (meio do contexto), recuperou `Xylo9-Zurich` sem
truncamento (`prompt_n` exacto) e a fronteira acima do limite devolveu
**HTTP 400 `exceed_context_size_error`** (nunca corte mudo). 100k e real nesta unit.

### 4.2 Ternary-Flint-40B `PQ2_0` — a escolha por medicao (e o que fica na unit)

Mesma engine, mesmas flags, `-c 100000` (comparacao 1-para-1 com §4.1):

| contexto | `PTQ1_0` prefill / decode | `PQ2_0` prefill / decode |
|---|---|---|
| 4 070 | 240,1 / 46,7 | **677,5 / 51,9** |
| 8 177 | 232,5 / 44,8 | **644,7 / 49,6** |
| 16 380 | 221,8 / 41,5 | **576,0 / 45,4** |
| 32 760 | 204,7 / 35,7 | **470,3 / 38,5** |
| 65 528 | 175,6 / 26,3 | **345,4 / 28,1** |
| 99 030 | 155,0 / 15,7 | **272,0 / 20,8** |

Tarefas curtas: decode **56,4-56,7 tok/s** (PTQ1_0: 50,7) e prefill 238-370.
Tool calling: **3/3** validos. Agulha a **99 576 tokens**: PASS, `prompt_n`
exacto, fronteira HTTP 400. VRAM: **12 837 MiB** usadas contra 11 149 do
`PTQ1_0` (+1 688 MiB) — folga de ~10 100 MiB, guarda de 1,5 GB cumprida.

**Decisao:** `flint-ternary.service` corre `PQ2_0`. O `PTQ1_0` fica em disco
como fallback explicito para cartas apertadas (é o unico que cabe ao lado de
um segundo modelo grande, e o ficheiro de 9,31 GiB citado na tabela de
partida), bastando trocar o `-m` da unit — nenhum outro flag muda.

### 4.3 PXA-Fusion4-35B `PXQ4` — `-c 32768 -ngl 99 -sm layer -ctk q8_0 -ctv f16`

Carga: `model size = 17,961 GiB (4,345 BPW)`, `KV buffer 553,44 MiB`,
`compute buffer 2 300,05 MiB` → **21 263 MiB usados, 1 644 MiB livres** (a
guarda de 1,5 GB do switch fica cumprida por 108 MiB).

| contexto | prefill tok/s | decode tok/s |
|---|---|---|
| 4 096 | 1 111,0 | 38,7 |
| 8 192 | 1 067,4 | 30,5 |
| 16 384 | 890,2 | 18,2 |
| 31 744 | 682,5 | 11,3 |

Tarefas: 55,8 tok/s decode medio. Tool calling: 3/3.

**Achado importante — `-fa on` e um desastre neste par (sm_61, qwen35moe PXQ4).**
Com a mesma unit apenas mudada de `-fa off` para `-fa on`:

| contexto | prefill `-fa on` | prefill `-fa off` | ratio |
|---|---|---|---|
| 4 096 | 144,0 | 1 111,0 | 7,7× |
| 8 192 | 82,3 | 1 067,4 | 13,0× |
| 16 384 | 44,2 | 890,2 | 20,1× |

E o prefill ainda por cima **degrada com o contexto** em `-fa on` (144 → 44),
enquanto em `-fa off` e quase plano (1 111 → 890). E o espelho exacto do que o
PXA ja documenta para MLA em sm_61 (`docs/KNOWN-ISSUES.md`: "the MLA
flash-attention path itself is 75-326 % SLOWER decode on sm_61 than fa-off …
sm_61 is fp16-starved (1:64 rate)"): aqui se e o caminho flash generico do
híbrido deltanet, e a carta e a P40 nunca medida. Por isso a unit
`fusion4.service` fica **`-fa off`**, com `--cache-type-v f16` (o cache V
quantizado exige `-fa on`: "Quantized V cache cannot be used without flash
attention").

### 4.4 Limite de contexto do Fusion4 numa P40

`-fa off` paga um compute buffer de atencao generica (2,3 GB a 32k, 3,4 GB a
49k). Medido:

| config | VRAM usada | folga | resultado |
|---|---|---|---|
| `-fa off -c 32768` (`-ub 1024`) | 21 263 MiB | 1 644 MiB | OK — e o que esta na unit |
| `-fa off -c 49152` (`-ub 1024`) | 22 423 MiB | 484 MiB | carrega, mas **viola** a guarda de 1,5 GB |
| `-fa off -c 65536` (`-ub 1024`) | — | — | `cudaMalloc failed: out of memory` — pede **4 508 MiB** de compute buffer |
| `-fa off -c 65536` (`-ub 512`, variante) | 21 737 MiB | 1 170 MiB | carrega (compute 2 285 MiB), mas continua **abaixo** da guarda |
| `-fa off -c 100000` (`-ub 512` e `1024`) | — | — | `failed to allocate compute buffers` (pede 7,16 GB) |
| `-fa on -c 100000` | 20 051 MiB | 2 856 MiB | carrega, prefill 44-144 tok/s (inutil) |

O compute buffer da atencao generica escala com `-ub` (2 285 MiB a `-ub 512`,
4 508 MiB pedidos a `-ub 1024` no mesmo `-c 65536`) — por isso a variante de
65 536 so aparece como nota, nao como config recomendada. O PXA imprime
`-ub 2048 [USER]` no resumo da celula P40 (`pxa-registry.cpp:537`), mas o
que vale e o `-ub` da linha de comandos; `PXA_AUTO_UB_RESERVE_MB=1600` nao
muda nada neste caminho (a escada 2048→256 so actua quando o *modelo* nao
cabe, e aqui cabe). **Para o Fusion4, 100k numa unica P40 nao e utilizavel**:
ou 32k rápido com a guarda respeitada, ou 100k com `-fa on` a 44-144 tok/s de
prefill. 100k fica entao para o Ternary-Flint (§4.1/4.2), que os serve a
272 tok/s de prefill e 20,8 de decode com 12,8 GB.

## 5. Guarda de VRAM (1,5 GB) com o 4B residente

Nada mudou no mecanismo: `ModelsCLI._check_vram_guard()` chama
`GpuMonitor.free_mb()` (via `nvidia-smi --query-gpu=memory.free` da GPU
`PCSALA_GPU_INDEX`, default 0) e recusa com codigo **3** quando a folga e
< 1 536 MiB, antes de mandar `systemctl start`. Como o `free` do nvidia-smi ja
desconta tudo o que esta na carta, a fraccao do **Bonsai 4B residente** (246
MiB de contexto CUDA do llama-server do slot residente) entra automaticamente
na conta — e e por isso que a reserva e uma *folga*, nao um orcamento do
modelo alvo.

Testes adicionados em `tests/test_gpu_expansion_2026_11.py`: recusa a 1 535
MiB e permissao a 1 536 MiB para `start` e `switch` dos dois novos, falha
fechada sem `nvidia-smi`, e `test_limiar_continua_1_5_gb` a fixar o limiar.
O `switch` dos novos modelos corre pelo caminho antigo: mede antes de mandar
`start` e volta a medir depois de libertar o slot (`_await_release`), porque
um `systemctl stop` regressa com a VRAM ainda presa.

```console
$ ./pcsala models switch flint-ternary-40b
Troca concluida: fusion4-35b -> flint-ternary-40b
```

Comportamento observado a 08/11 enquanto se procurava um estado com folga
< 1,5 GB para gravar uma recusa ao vivo: com o Fusion4 a `-c 65536` (que nao
cabe), a unit **entrou em crash-loop** (`Restart=on-failure`, `restart counter
is at 5`); a variante `-c 49152` (22 423 MiB usados, **484 MiB livres**) era o
estado ao vivo certo para `pcsala models start flint-ternary-40b` devolver 3,
mas nesse intervalo outra sessao da maquina (sudo de `igor`, externa a esta)
repux o primario `sudo systemctl start bonsai2-27b.service` e a janela
fechou-se. O `Conflicts=bonsai2-27b.service` declarado na unit nova
**funcionou na direccao inversa**: ao subir o Bonsai, o systemd parou o
Fusion4 sem intervencao manual — a exclusividade do slot e bidireccional.
A recusa por folga fica portanto coberta por assercoes (10 em
`tests/test_gpu_expansion_2026_11.py` + 12 em `tests/test_vram.py`), com o
mecanismo intacto e sem alteracoes: `start` e `switch` medem antes de mandar
`systemctl start` e o `switch` volta a medir depois de libertar o slot.

## 6. Como usar

```bash
# trocar para o Ternary-Flint a 100k
./pcsala models switch flint-ternary-40b      # ou: ia solo flint-ternary
python3 scripts/bench_gpu_slot.py flint tudo

# trocar para o Fusion4 a 32k
./pcsala models switch fusion4-35b            # ou: ia solo fusion4
python3 scripts/bench_gpu_slot.py fusion4 tudo

# so um degrau da escala, ou um endpoint explicito
python3 scripts/bench_gpu_slot.py flint escala --de 65536
python3 scripts/bench_gpu_slot.py flint tarefas --endpoint http://127.0.0.1:8101
```

## 7. Fica por fazer / riscos

- `PTQ1_0` e `PQ2_0` do Ternary-Flint foram **calibrados** (README) mas nao
  foram validados por perplexidade nesta maquina; a valida aqui foi estrutural
  (carregam, geram, respondem, ferramenta, agulha). Para escolher o quant por
  qualidade falta `llama-perplexity` contra um corpus de codigo.
- O Fusion4 corre com cabeca MTP inerte: `--spec-type mtp:n_max=1` esta
  documentado pelo fabricante (+7 % decode a 32k) mas nao foi medido aqui,
  porque com `-fa off` o budget de VRAM nao da para o contexto draft extra.
- `pcsala models` so conhece 9 modelos; o resto da frota (qwen36, glm47,
  flint APEX-I, …) continua acessivel apenas pelo `ia`.
- O dispatcher `cli.py` continua sem ligar `models vram`/`gen-llama-swap`
  (registado no PROJECT_STATE; nao e caminho de producao).
- As units ficam `disabled`: arrancam so por `ia`/`pcsala`, nunca ao boot.
- `Restart=on-failure` + um `-c` que nao cabe e um ciclo lento (cada tentativa gasta
  ~90 s a ler 18 GB da sdb1 antes do `cudaMalloc` dizer nao). Mitigado com
  `StartLimitIntervalSec=900` + `StartLimitBurst=2` nas duas units — vistos a
  08/11 no `-c 65536` do Fusion4.
