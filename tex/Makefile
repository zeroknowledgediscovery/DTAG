TEX := main
LATEXMK ?= latexmk

.PHONY: all clean distclean

all:
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error $(TEX).tex

clean:
	$(LATEXMK) -c $(TEX).tex

distclean:
	$(LATEXMK) -C $(TEX).tex
