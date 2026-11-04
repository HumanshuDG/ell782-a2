# Build all PDF deliverables:  make        (needs pdflatex; run twice for longtable widths)
DOCS = isa architecture memory_map listing pipeline_traces validation
all: $(DOCS:=.pdf)
%.pdf: %.tex common.tex $(wildcard generated/*.tex)
	pdflatex -interaction=nonstopmode -halt-on-error $<
	pdflatex -interaction=nonstopmode -halt-on-error $<
clean:
	rm -f *.aux *.log *.out *.toc
distclean: clean
	rm -f $(DOCS:=.pdf)
.PHONY: all clean distclean
