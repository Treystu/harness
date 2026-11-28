import Pilot
open Pilot

example : (adjudicate ⟨1, .defect, .material⟩ 0 0).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 0 299).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 0 300).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 0 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 0 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1 0).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1 299).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1 300).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 349 0).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 349 299).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 349 300).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 349 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 349 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 350 0).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 350 299).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 350 300).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 350 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 350 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 351 0).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 351 299).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 351 300).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 351 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 351 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 649 0).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 649 299).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 649 300).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 649 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 649 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 650 0).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 650 299).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 650 300).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 650 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 650 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 651 0).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 651 299).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 651 300).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 651 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 651 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 999 0).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 999 299).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 999 300).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 999 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 999 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1000 0).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1000 299).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1000 300).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1000 301).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1000 1000).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 486 455).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 32 638).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 687 996).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 82 876).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 298 332).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 654 230).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 647 641).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 301 106).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 417 353).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 252 556).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 807 131).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 548 668).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 978 582).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 874 415).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 403 709).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 377 380).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 209 505).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 853 76).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 586 743).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 242 729).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 791 810).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 108 360).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 993 616).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 407 262).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 538 374).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 266 37).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 426 303).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 28 181).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 469 347).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 185 136).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 138 216).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 960 637).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 350 811).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 909 845).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 798 475).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 635 791).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 346 412).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 619 770).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 587 800).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 463 440).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 95 853).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 447 726).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 538 0).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 506 139).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 608 661).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 615 41).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 545 205).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 555 897).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 569 85).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 430 657).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 786 285).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 715 605).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 743 841).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 511 118).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 486 676).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 438 583).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 330 407).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 998 576).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 975 750).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 793 105).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 272 300).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 259 180).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 340 805).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 678 258).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 522 595).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 991 726).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 621 170).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 216 353).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 216 567).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 632 532).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 934 219).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 394 294).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 25 463).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 156 456).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 367 443).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 818 781).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 565 642).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 441 281).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 738 104).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 9 406).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 798 923).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 1000 622).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 908 780).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 899 629).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 42 974).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 644 531).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 331 141).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 797 405).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 711 146).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 986 461).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 226 93).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 992 105).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 138 903).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 780 821).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 277 850).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 597 38).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 56 643).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 39 843).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 625 470).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 834 992).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 748 14).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 575 62).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 133 826).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 267 187).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 642 651).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 800 527).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 200 543).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 161 68).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 504 958).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 451 268).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 327 274).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 58 29).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 923 361).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 878 539).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 807 555).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 319 18).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 557 990).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 448 990).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 352 794).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 290 667).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 814 75).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 823 778).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 871 258).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 98 361).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 671 403).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 483 162).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 105 331).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 952 837).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 82 494).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 629 517).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 932 193).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 743 615).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 14 0).verdict = .notReal := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 307 548).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 927 26).verdict = .real := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 466 643).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 165 708).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 774 661).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 567 907).verdict = .defer := by decide
example : (adjudicate ⟨1, .defect, .material⟩ 877 562).verdict = .defer := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, true⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, true⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, true⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, true⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, true⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, true⟩] = (.defer, 4, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, true⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, true⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .real, 900, 100, true⟩] = (.fail, 2, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, true⟩] = (.defer, 4, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩] = (.fail, 3, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, true⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, true⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, true⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .real, 900, 100, true⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .real, 900, 100, true⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, true⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, true⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, true⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, true⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, true⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, true⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩] = (.defer, 4, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, true⟩] = (.defer, 1, true) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .real, 900, 100, true⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩] = (.fail, 3, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, true⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, true⟩] = (.fail, 2, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩] = (.defer, 4, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, true⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩] = (.fail, 2, false) := by decide
example : aggregate [⟨⟨1, .defect, .supporting⟩, .real, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, true⟩] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .defer, 900, 100, false⟩, ⟨⟨1, .reassurance, .supporting⟩, .real, 900, 100, false⟩, ⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [⟨⟨1, .reassurance, .supporting⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .reassurance, .material⟩, .defer, 900, 100, false⟩] = (.defer, 1, true) := by decide
example : aggregate [] = (.pass, 5, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩, ⟨⟨1, .defect, .supporting⟩, .real, 900, 100, false⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .notReal, 900, 100, false⟩] = (.fail, 3, false) := by decide
example : aggregate [⟨⟨1, .reassurance, .material⟩, .real, 900, 100, false⟩, ⟨⟨1, .defect, .material⟩, .notReal, 900, 100, true⟩, ⟨⟨1, .defect, .supporting⟩, .defer, 900, 100, false⟩] = (.defer, 4, false) := by decide
example : nonJevFallback .pass = (.pass, 0, false, true) := by decide
example : nonJevFallback .fail = (.fail, 0, false, true) := by decide
example : nonJevFallback .defer = (.defer, 0, true, true) := by decide
