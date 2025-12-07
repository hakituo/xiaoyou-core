# 编译与图表生成说明（Windows）

- 安装 TeX 发行版：MiKTeX 或 TeX Live（Windows），确保包含 `bibtex`、`latexmk`。
- 进入 `paper` 目录后执行：

```
latexmk -pdf -silent paper.tex
```

- 如遇到参考文献未解析，手动执行：

```
pdflatex paper.tex
bibtex paper
pdflatex paper.tex
pdflatex paper.tex
```

- 图表数据生成：在 `paper/experiment/scripts` 下运行需要的脚本，数据会写入 `experiment/experiment_results/data`，随后执行：

```
python paper/experiment/scripts/generate_charts.py
```

- 论文引用的图表分布在：
  - `output/experiment_results/charts/`
  - `experiment/experiment_results/charts/`

## 依赖包（LaTeX）

- `amsmath, amssymb`
- `graphicx, booktabs, tabularx`
- `xcolor, listings, placeins, microtype`
- `geometry`
- `newtxtext, newtxmath`
- `hyperref, cleveref`

## 维护建议

- 两栏版式下优先使用 `\columnwidth` 控制图表宽度，长公式使用 `aligned/split` 控制换行。
- 章节间添加 `\FloatBarrier` 控制图漂移（已在文档关键段落添加）。
- 参考文献样式为 `IEEEtran`，BibTeX 数据位于 `paper/references.bib`。
