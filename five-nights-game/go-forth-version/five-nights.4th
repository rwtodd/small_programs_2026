<<" random strings ">> <activate-extensions>

\ library stuff
: incvar ( var -- ) dup @ 1 + swap ! ;
: @for-each (| arr xt | -- ?? ) arr @len 0 do arr i @ xt execute loop ;
: <enum> ( s1 s2 ... n -- )
    <strings> 0 swap [ over swap constant 1 + ] @for-each drop ;
: <enum-bits> ( s1 s2 ... n -- )
    <strings> 1 swap [ over swap constant 2 * ] @for-each drop ;

\ Basic Game Status 
12 " #rounds" constant
0 " round" variable
<<" 
    12:00AM 12:30AM 1:00AM 1:30AM 2:00AM 2:30AM 
    3:00AM 3:30AM 4:00AM 4:30AM 5:00AM 5:30AM
">> <strings> [ swap @ ] " round-name" variable-does
false " LOST-GAME?" variable

\ power starts at 100... the power die determines how much power is lost subject to the
\ presense of a power drain card
100 " POWER" variable
5 " POWER-DRAIN-AMT" constant 
0 " #POWER-DRAINS" variable  \ how many power drains are active this round?
<< 0 0 5 5 10 10 >> <ints> [ @select ] " power-die" variable-does

\ *** CARD TYPES ***
<<" c(Animatronic) c(EmptyRoom) c(PowerDrain) c(ArrowDown) c(ArrowRight) c(DoubleRight) c(NO-CARD) ">> <enum>

<< 
    " Animatronic!"   
    " Empty Room"  
    " Power Drain"  
    " What Was That? Down Arrow"
    " What Was That? Right Arrow"
    " What Was That? Double Right Arrow"
    " Not a card! ERROR"
>> <strings> [ swap @ ] " card-name" variable-does
  
\ initialize the game
4 things " piles" constant
: cards, ( n v -- v x n ) swap 1 DO dup LOOP ;
: init-game ( -- )
  100 power !    false lost-game? !
  \ set up the initial cards
  << 
      11 c(EmptyRoom)   cards,
       7 c(PowerDrain)  cards,
       7 c(ArrowDown)   cards,
      12 c(ArrowRight)  cards,
       7 c(DoubleRight) cards,
  >> <ints> dup @shuffle
  0 ints  10  0 DO over i @  @push LOOP  << c(Animatronic) dup >> <@push> dup @shuffle piles 0 !  \ stack 0 -- 10 cards plus 2 animatronics
  0 ints  21 10 DO over i @  @push LOOP  c(Animatronic) @push             dup @shuffle piles 1 !  \ stack 1 -- 11 cards plus 1 animatronic
  0 ints  32 21 DO over i @  @push LOOP  c(Animatronic) @push             dup @shuffle piles 2 !  \ stack 2 -- 11 cards plus 1 animatronic
  0 ints  44 32 DO over i @  @push LOOP                                   dup @shuffle piles 3 !  \ stack 3 -- 12 cards, no animatronics
  drop \ dropping the full-shuffled-deck
  ;

: .round-header ( -- ) 
  cr cr
  " ================================\n" type
  " Round: %2d/12 (%s)\n" << round @ dup 1 + swap round-name >> sprintf type
  " Power: %3d%%\n" << power @ >> sprintf type
  " Pile Sizes: [%2d %2d %2d %2d]\n" << 4 0 DO piles i @ @len LOOP >> sprintf type
  " ================================\n\n" type
  ;

: pull-one-card!  ( pile# -- card ) \ also saves the pile that got pulled from
  piles over @  ( n pile ) 
  dup @len 0> IF @pop >r piles rot ! r> 
             ELSE drop drop c(NO-CARD)
	     THEN  ;


: draw-from-pile ( n -- arr )
  \ draws card(s) from the specified pile, saving the new state in `piles`
  0 ints 
  BEGIN
     over pull-one-card!  ( n arr card )
     dup c(PowerDrain) = IF  #power-drains incvar THEN
     dup c(NO-CARD) <> IF tuck @push swap THEN ( n arr card )
     c(Animatronic) <> 
  UNTIL
  nip
  ;

: draw-each-pile ( -- drawn-piles ) << 4 0 DO i draw-from-pile LOOP >> <things> ;

: ->digit ( str -- int ) ORD  [[ " 0" ORD ]] literal  - ; 
: 0-9? ( n -- bool ) dup 0 >= swap 10 < and ;
: read-digit ( -- n ) 
    read-line trim"" 
    dup blank""? IF drop (tail-call) THEN \ silently skip blank lines
    dup len"" 1 = IF ->digit dup 0-9? IF exit THEN THEN 
    drop
    " Please enter a 1-digit number (try again)\n" type
    (tail-call) ;

: count-cards ( piles -- n )
  0 (| ctr |)  
  dup @len 0 DO   
     dup i @ @len ctr + ctr!
  LOOP 
  drop ctr ;

\ get the nth card of the drawn cards, and also set that drawn card to NO-CARD
: nth-card! ( drawn-piles n -- pile# card )
  1 - ( zero indexing )
  (| drawn idx |)
  4 0 DO
     drawn i @ (| cp |) cp @len idx > IF   i   cp idx @   c(NO-CARD) cp idx !  EXIT 
                                     ELSE  idx cp @len - idx! THEN
  LOOP 
  \ just return no-card in pile 0 if the index was too big...
  0 c(NO-CARD) ;

: react-to-card ( drawn-piles n --  ) 
  \ use energy...
  power-die   5 #power-drains @ *   +
  " Using %2d%% energy to react...\n" << over >> sprintf type
  power @ swap - power !
  nth-card! c(Animatronic) = IF
     " Shuffling Animatronic back into pile %d!\n" << over 1 + >> sprintf type
     piles over @   c(Animatronic) @push   dup @shuffle   piles rot !
  ELSE drop ( all other reactions just drop the card! ) THEN ;

: query-user ( drawn-piles -- )
  dup count-cards 
  " Drew %d cards\n" << over >> sprintf type
  0 (| max# picked |)
  BEGIN
    " Pick first of two cards to react to (0 for none): " type
    read-digit 
    dup max# <= IF leave THEN
    drop " Highest number is %d (try again)\n" << max# >> sprintf type
  AGAIN
  dup picked! 0= IF drop exit THEN 
  dup picked react-to-card

  BEGIN
    " Pick second of two cards to react to (0 for none): " type
    read-digit
    dup max# <=  over picked <> and IF leave THEN
    drop " Highest number is %d and can't pick %d a second time (try again)\n" << max# picked >> sprintf type
  AGAIN
  dup picked! 0= IF drop exit THEN
  picked react-to-card
  ; 

: move-over-to-pile ( card p# -- )
    over c(NO-CARD) = IF drop drop EXIT THEN  \ nothing to do with non-cards
    dup 4 >= IF
       \ announce whatever card gets discarded... animatronics are losses
       drop  " Moved the '%s' card past the piles!\n" << over card-name >> sprintf type 
       c(Animatronic) = IF  true lost-game? ! THEN
    ELSE
       \ put the card into the pile and shuffle... announce if animatronic
       over c(Animatronic) = IF " Animatronic moved to pile %d!\n" << over 1 + >> sprintf type THEN
       piles over @ rot @push dup @shuffle piles rot !
    THEN ;

: retire-1-card ( card pile -- )
  swap CASE 
    c(Animatronic) OF  c(Animatronic) swap 1 + move-over-to-pile  ENDOF
    c(ArrowDown) OF dup pull-one-card! 
        dup c(NO-CARD) <> IF 
           " Arrow Down card pulls a '%s' from pile %d!\n" << over card-name 3 pick 1 + >> sprintf type
           swap recur \ immediately retire this card
	ELSE
	   drop drop \ clean up the stack since there's nothing to do!
	THEN
    ENDOF
    c(ArrowRight) OF dup pull-one-card! swap 1 + move-over-to-pile ENDOF
    c(DoubleRight) OF dup pull-one-card! swap 2 + move-over-to-pile ENDOF
    ( default ) drop
  ENDCASE ;

: retire-cards ( drawn-piles -- ) 
  -1 3 DO \ loop over the piles right-to-left
     dup i @
     dup @len 0 DO
        dup i @  j retire-1-card
     LOOP drop
  LOOP drop ;

: .drawn-cards ( drawn-piles -- )
  \ for each stack, draw card(s)
  0 (| ctr |)
  4 0 DO
     " Pile %d:\n" i 1 + 1 sprintf type
     dup i @   [ (| crd |) ctr 1 +  ctr!   "   (%d) %s\n" << ctr crd card-name >> sprintf type ] @for-each
  LOOP drop ;

: pile-empty? ( pile# -- bool ) piles swap @ @len 0= ;
: pile-swap ( pile#1 pile#2 -- )  
    over piles swap @ swap rot ( pile1 p#2 p#1 ) 
    over piles swap @ swap ( pile1 p#2  pile2 p#1 )  
    piles swap !   piles swap ! ;
    
: consolidate-piles ( -- ) \ move over piles if any are empty
  -1 2 DO   
     i pile-empty? invert IF   
        \ move this non-empty pile as far right as possible 
	4 i 1 + DO  i pile-empty? IF  i dup 1 - pile-swap  THEN  LOOP
     THEN 
  LOOP ;

: play-round ( -- )
  0 #power-drains ! \ reset the number of power-drains we have
  draw-each-pile dup .drawn-cards 
  power @ 0> IF 
     dup query-user 
  ELSE
     " Out of power... hoping for the best!\n" type
  THEN
  retire-cards
  ; 

: play-game ( -- )
   " \n\n\n===== F I V E * N I G H T S * A T * F R E D D Y ' S =====\n\n" type
   init-game
   #rounds 0 DO
      i round !
      .round-header cr
      play-round
      lost-game? @ IF leave THEN
      consolidate-piles
   LOOP
   lost-game? @ IF " You lost!\n" ELSE " You won!!!\n" THEN type
   ;

play-game
